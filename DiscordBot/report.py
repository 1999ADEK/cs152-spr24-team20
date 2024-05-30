from enum import Enum, auto
import discord
import re

#Additional imports
from discord.ui import Button, View
from captcha.image import ImageCaptcha
import random
import string
import io

class State(Enum):
    REPORT_START = auto()
    AWAITING_MESSAGE = auto()

    # Currently not needed bc if message is identified then we automatically await category
    MESSAGE_IDENTIFIED = auto()
    
    REPORT_COMPLETE = auto()

    # Additional states for categories and subcategories
    AWAITING_CATEGORY = auto()
    AWAITING_SUBCATEGORY = auto()
    AWAITING_SUBSUBCATEGORY = auto()
    FINISHED_CATEGORY_SELECTIONS = auto()
    AWAITING_DESCRIPTION = auto()

    # Waiting for identity verification per report
    AWAITING_VERIFICATION = auto()

class CategoryButton(Button):
    def __init__(self, category, report):
        super().__init__(label=category, style=discord.ButtonStyle.primary)
        self.category = category
        self.report = report

    async def callback(self, interaction: discord.Interaction):
        self.report.category = self.category
        self.report.state = State.AWAITING_SUBCATEGORY
        sub_category_buttons = View()
        for sub_cat in self.report.SUB_CATEGORIES[self.category]:
            sub_category_buttons.add_item(SubCategoryButton(sub_cat, self.category, self.report))
        await interaction.response.edit_message(content=f"You selected {self.category}. Please select a sub-category:", view=sub_category_buttons)

class SubCategoryButton(Button):
    def __init__(self, sub_category, category, report):
        super().__init__(label=sub_category, style=discord.ButtonStyle.secondary)
        self.category = category
        self.sub_category = sub_category
        self.report = report

    async def callback(self, interaction: discord.Interaction):
        self.report.sub_category = self.sub_category
        sub_sub_category_buttons = View()
        sub_sub_categories = self.report.SUB_SUB_CATEGORIES.get(self.sub_category, [])
        for sub_sub_cat in sub_sub_categories:
            sub_sub_category_buttons.add_item(SubSubCategoryButton(sub_sub_cat, self.sub_category, self.category, self.report))  
        
        # If there are no additional categories to select. End the report
        if len(sub_sub_categories) == 0:
            self.report.state = State.FINISHED_CATEGORY_SELECTIONS
            await interaction.response.edit_message(content=f"'{self.category}: {self.sub_category}' selected.", view=None)

            # Need this fake message to call handle_dm so that it will mark the report as complete and remove it from the reports dictionary
            # Should mark as pending for moderators when implementing moderator flow
            fake_message = type('FakeMessage', (object,), {"author": interaction.user, "content": "end_report", "channel": interaction.channel})
            await self.report.client.handle_dm(fake_message)
        else:
            self.report.state = State.AWAITING_SUBSUBCATEGORY
            await interaction.response.edit_message(content=f"You selected '{self.sub_category}'. Please select a clarifying category:", view=sub_sub_category_buttons)

class SubSubCategoryButton(Button):
    def __init__(self, sub_sub_category, sub_category, category, report):
        super().__init__(label=sub_sub_category, style=discord.ButtonStyle.secondary)
        self.sub_sub_category = sub_sub_category
        self.sub_category = sub_category
        self.category = category  
        self.report = report

    async def callback(self, interaction: discord.Interaction):
        self.report.sub_sub_category = self.sub_sub_category
        self.report.state = State.FINISHED_CATEGORY_SELECTIONS
        await interaction.response.edit_message(content=f"'{self.category}: {self.sub_category}: {self.sub_sub_category}' selected.", view=None)

        # Similar to SubCategoryButton, handle ending the report
        fake_message = type('FakeMessage', (object,), {"author": interaction.user, "content": "end_report", "channel": interaction.channel})
        await self.report.client.handle_dm(fake_message)


class Report:
    START_KEYWORD = "report"
    CANCEL_KEYWORD = "cancel"
    HELP_KEYWORD = "help"
    
    CATEGORIES = ["Violence", "Sexual", "Copyright", "Harassment", "Misleading", "Inflammatory"]

    SUB_CATEGORIES = {
        "Violence": ["Terrorism", "Threats", "Glorification", "Graphic", "Self-Harm"],
        "Sexual": ["Explicit Sexual Activity", "Nudity", "Explicit Text", "Sexual Violence"],
        "Copyright": ["Plagiarism", "Defamation", "Counterfeit", "Privacy Issues"],
        "Harassment": ["Bullying", "Child Abuse"],
        "Misleading": ["Clickbait", "Scams", "Manipulated Media", "Hoax"],
        "Inflammatory": ["Hate Speech", "Polarizing", "Sensationalism", "Cultural Sensitivity"]
    }

    SUB_SUB_CATEGORIES = {
        "Terrorism": ["Recruitment", "Promotion", "Propaganda"],
        "Self-Harm": ["Suicidal", "Promotion", "Drug Abuse"],
        "Sexual Violence": [],
        "Bullying": ["Personal Attacks", "Cyberstalking", "Targeting"],
        "Child Abuse": ["Grooming", "Physical Abuse", "Emotional Abuse"],
        "Scams": [],
        "Manipulated Media": ["Deep Fake", "Edited", "Misattributed", "Out of Context"],
        "Hate Speech": [],
        "Polarizing": ["Explicit", "Edited", "Symbols & Gestures"],
        "Sensationalism": [],
        "Cultural Sensitivity": ["Appropriation", "Stereotypes", "Symbols & Gestures"],
    }

    def __init__(self, client):
        self.state = State.REPORT_START
        self.client = client
        self.message = None

        self.category = None
        self.sub_category = None
        self.sub_sub_category = None
        self.message_author = None
        self.report_description = None
        self.captcha_answer = None
        self.reporter_id = None
        self.moderator_decision_explanation = None
        self.moderator_category = None



    def generate_captcha(self):
        image = ImageCaptcha(width=280, height=90)
        letters = string.ascii_uppercase + string.digits
        captcha_text = ''.join(random.choice(letters) for i in range(6))  # Generate a random 6-character text
        data = image.generate(captcha_text)
        return data, captcha_text

    async def send_captcha_challenge(self, channel):
        """Generate and send a CAPTCHA challenge."""
        image_data, self.captcha_answer = self.generate_captcha()
        with io.BytesIO(image_data.getvalue()) as image_file:
            image_file.seek(0)
            file = discord.File(fp=image_file, filename='captcha.png')
            await channel.send("Thank you for starting the reporting process. Say `help` at any time for more information. \n\nTo continue, please solve this CAPTCHA to verify you are human:", file=file)

    async def handle_message(self, message):
        '''
        This function makes up the meat of the user-side reporting flow. It defines how we transition between states and what 
        prompts to offer at each of those states. You're welcome to change anything you want; this skeleton is just here to
        get you started and give you a model for working with Discord. 
        '''

        # Save reporter_id
        self.reporter_id = message.author.id

        if message.content == self.CANCEL_KEYWORD:
            self.state = State.REPORT_COMPLETE
            return ["Report cancelled."]
        
        if self.state == State.REPORT_START:
            self.state = State.AWAITING_VERIFICATION
            await self.send_captcha_challenge(message.channel)
            return []
        
        if self.state == State.AWAITING_VERIFICATION:
            if message.content.strip().upper() == self.captcha_answer:
                self.state = State.AWAITING_MESSAGE
                reply = "CAPTCHA verified successfully. \n\n"
                reply += "Please proceed with your report by copy pasting the link to the message you want to report.\n"
                reply += "You can obtain this link by right-clicking the message and clicking `Copy Message Link`."
                return [reply]
            else:
                return ["Incorrect CAPTCHA. Please try again."]
        
        if self.state == State.AWAITING_MESSAGE:
            # Parse out the three ID strings from the message link
            m = re.search('/(\d+)/(\d+)/(\d+)', message.content)
            if not m:
                return ["I'm sorry, I couldn't read that link. Please try again or say `cancel` to cancel."]
            guild = self.client.get_guild(int(m.group(1)))
            if not guild:
                return ["I cannot accept reports of messages from guilds that I'm not in. Please have the guild owner add me to the guild and try again."]
            channel = guild.get_channel(int(m.group(2)))
            if not channel:
                return ["It seems this channel was deleted or never existed. Please try again or say `cancel` to cancel."]
            try:
                message = await channel.fetch_message(int(m.group(3)))
            except discord.errors.NotFound:
                return ["It seems this message was deleted or never existed. Please try again or say `cancel` to cancel."]

            # Here we've found the message - it's up to you to decide what to do next!
            self.state = State.AWAITING_CATEGORY
            category_buttons = View()
            for category in self.CATEGORIES:
                category_buttons.add_item(CategoryButton(category, self))
            

            self.message = message
            self.message_author_name = message.author.name
            return [(("I found this message:\n```" + message.author.name + ": " + message.content + "```" + "Please select the problem:"), category_buttons)]
        
        if self.state == State.FINISHED_CATEGORY_SELECTIONS:
            self.state = State.AWAITING_DESCRIPTION
            return ["Providing further clarification details about the nature of this violation, your report will be prioritized. Suggested topics could include but are not limited to: How did you come across this content? Is this an isolated incident, or part of a larger pattern you’ve observed? What action do you believe should be taken regarding this content?"]
        
        if self.state == State.AWAITING_DESCRIPTION:
            self.report_description = message.content  
            self.state = State.REPORT_COMPLETE 
            return [f"Thank you for providing additional details. Your report is now complete and will be reviewed by our moderation team."]
            
        
        # The following states are no longer needed because the category and subcategory are chain selected need for state management.
                
        # if self.state == State.AWAITING_CATEGORY:
        #     if message.content in self.CATEGORIES:
        #         self.category = message.content
        #         self.state = State.AWAITING_SUBCATEGORY
        #         return ["Please select a sub-category:", ", ".join(self.SUB_CATEGORIES[self.category])]
        #     else:
        #         return ["Invalid category. Please try again or say `cancel` to cancel."]

        # if self.state == State.AWAITING_SUBCATEGORY:
        #     if message.content in self.SUB_CATEGORIES[self.category]:
        #         self.sub_category = message.content
        #         self.state = State.REPORT_COMPLETE
        #         return ["Thank you for your report. Our moderation team will review this post. You may choose to mute or block the user."]
        #     else:
        #         return ["Invalid sub-category. Please try again or say `cancel` to cancel."]
        
        # if self.state == State.AWAITING_SUBSUBCATEGORY:
        #     if message.content in self.SUB_SUB_CATEGORIES[self.sub_category]:
        #         self.sub_sub_category = message.content
        #         self.state = State.REPORT_COMPLETE
        #         return ["Thank you for your report. Our moderation team will review this post. You may choose to mute or block the user."]
        #     else:
        #         return ["Invalid sub-sub-category. Please try again or say `cancel` to cancel."]
        
        if self.state == State.REPORT_COMPLETE:
            return []

        return ["An error has occurred. Make sure than any pending reports are completed or canceled. Please restart the reporting process."]

    def report_complete(self):
        return self.state == State.REPORT_COMPLETE
    


    

