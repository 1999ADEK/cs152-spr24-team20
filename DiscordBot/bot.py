# bot.py
import discord
from discord.ext import commands
import os
import json
import logging
import re
import requests
from report import Report
import pdb
import asyncio
from collections import OrderedDict
import heapq
import datetime
import random
from utils import visualize_heap
from openai import OpenAI
from googleapiclient import discovery


# Set up logging to the console
logger = logging.getLogger('discord')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

# Placeholdler name for json file of precomputed SybilRank scores for each Discord ID
sybilrank_scores_file = 'SybilDetection/sybil_score.json'

# There should be a file called 'tokens.json' inside the same folder as this file
token_path = 'tokens.json'
if not os.path.isfile(token_path):
    raise Exception(f"{token_path} not found!")
with open(token_path) as f:
    # If you get an error here, it means your token is formatted incorrectly. Did you put it in quotes?
    tokens = json.load(f)
    discord_token = tokens['discord']
    openai_api_key = tokens['openai']
    perspective_api_key = tokens['perspective']


class ModBot(discord.Client):
    def __init__(self): 
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='.', intents=intents)
        self.group_num = None
        self.mod_channels = {} # Map from guild to the mod channel id for that guild
        self.reports = {} # Map from user IDs to the state of their report

        # A queue to handle reports of both harm types
        self.report_queue = []
        # Create dummy reports at initialization for demo purposes
        for _ in range(1):
            heapq.heappush(
                self.report_queue,
                (random.random(), datetime.datetime.now(), None),
            )
        # A queue to handle reports of suggestive harms
        self.suggestive_harm_dict = OrderedDict()

    async def setup_hook(self):
        '''
        Setup a background task.
        '''
        self.bg_task = self.loop.create_task(self.handle_report())
    
    async def on_ready(self):
        print(f'{self.user.name} has connected to Discord! It is these guilds:')
        for guild in self.guilds:
            print(f' - {guild.name}')
        print('Press Ctrl-C to quit.')

        # Parse the group number out of the bot's name
        match = re.search('[gG]roup (\d+) [bB]ot', self.user.name)
        if match:
            self.group_num = match.group(1)
        else:
            raise Exception("Group number not found in bot's name. Name format should be \"Group # Bot\".")

        # Find the mod channel in each guild that this bot should report to
        for guild in self.guilds:
            for channel in guild.text_channels:
                if channel.name == f'group-{self.group_num}-mod':
                    self.mod_channels[guild.id] = channel
                    # A temporary fix to directly access guild id
                    # TODO: Access this info from Report
                    self.guild_id = guild.id
        

    async def on_message(self, message):
        '''
        This function is called whenever a message is sent in a channel that the bot can see (including DMs). 
        Currently the bot is configured to only handle messages that are sent over DMs or in your group's "group-#" channel. 
        '''
        # Ignore messages from the bot 
        if message.author.id == self.user.id:
            return

        # Check if this message was sent in a server ("guild") or if it's a DM
        channel = message.channel
        if isinstance(channel, discord.TextChannel):
            await self.handle_channel_message(message)
        elif isinstance(channel, discord.DMChannel):
            await self.handle_dm(message)
        elif isinstance(channel, discord.Thread):
            await self.handle_appeal(message)

    async def handle_dm(self, message):
        # Handle a help message
        if message.content == Report.HELP_KEYWORD:
            reply =  "Use the `report` command to begin the reporting process.\n"
            reply += "Use the `cancel` command to cancel the report process.\n"
            await message.channel.send(reply)
            return

        author_id = message.author.id
        responses = []

        # Only respond to messages if they're part of a reporting flow
        if author_id not in self.reports and not message.content.startswith(Report.START_KEYWORD):
            return

        # If we don't currently have an active report for this user, add one
        if author_id not in self.reports:
            self.reports[author_id] = Report(self)

        # Let the report class handle this message; forward all the messages it returns to uss
        responses = await self.reports[author_id].handle_message(message)

        # Send all the responses we got from the report class, edited to use view with buttons
        for response in responses:
            if isinstance(response, tuple):
                content, view = response
                await message.channel.send(content, view=view)  # Send message with view
            else:
                await message.channel.send(response)  # Send normal text message

        # If the report is complete or cancelled, remove it from our map
        if self.reports[author_id].report_complete():
            report = self.reports.pop(author_id)
            # If the report is cancelled, do nothing
            if report.report_description is None:
                return
            # Otherwise, add it to the report queue
            # Reports with lower SybilRank scores are given higher priority
            # For those with the same score, priority is determined on a first-come, first-serve basis
            heapq.heappush(
                self.report_queue,
                (self.get_sybilrank_score(report), datetime.datetime.now(), report)
            )
            vis_filename = visualize_heap(self.report_queue, highlight_report=report)
            mod_channel = self.mod_channels[self.guild_id]
            await mod_channel.send(
                "=============================\n"
                "A report has been added to the queue. " +
                "Based on its Sybil score, it is currently positioned at this location in the heap:\n" +
                "(the lower the score, more trustworthy the reporter is, and the higher the priority of the report)"
            )
            await mod_channel.send(file=discord.File(vis_filename))
            os.remove(vis_filename)


    def get_sybilrank_score(self, report):
        # TODO: We need to implement this in milestone 3
        # Milestone 2: randomly assign a number as score
        # Milestone 3: Search for reporter's ID (same as author ID?)
        # and return SybilRank score
        
        with open(sybilrank_scores_file) as f:
            scores = json.load(f)
            if str(report.reporter_id) in scores:
                return scores[str(report.reporter_id)]
            else:
                # not sure what to do here
                return random.random()
    
    def generate_prompt(self, post):
        PROMPT = """### Instructions:

        Please classify the following post based on its content. Determine whether it falls under "immediate harm" or "suggestive harm" according to the criteria outlined in the Reporting Guide. Use the definitions below to make your classification:

        Immediate Harm: Content that poses an urgent and direct threat to individuals' safety and well-being, requiring immediate action. This includes:

        - Violence: Terrorism, threats, glorification of violence, graphic violence, self-harm (including suicidal content and promotion of drug abuse).
        - Sexual: Explicit sexual activity, nudity, explicit text, sexual violence.
        - Harassment: Bullying, child abuse (including personal attacks, cyberstalking, targeting, grooming, physical, and emotional abuse).
        - Copyright: Plagiarism, defamation, counterfeit, privacy issues.


        Suggestive Harm: Content that indirectly or potentially poses a threat or contributes to harmful situations but may not require immediate action. This includes:

        - Misleading: Clickbait, scams, manipulated media (deep fake, edited, misattributed, out of context), hoaxes.
        - Inflammatory: Hate speech, polarizing content, sensationalism, cultural insensitivity (including appropriation, stereotypes, symbols, and gestures).

        ### Examples:

        Post 1:
        "Join our cause! Let's fight back against the oppressors with any means necessary. #RevolutionNow"
        Classification: Immediate Harm (Violence - Threats)

        Post 2:
        "Check out this amazing new product! Only $1 for a limited time! [link] #Discount #Sale"
        Classification: Suggestive Harm (Misleading - Clickbait)

        Post 3:
        "Happy to share my latest artwork, even though someone else is trying to sell it as an NFT without my permission. #ArtTheft"
        Classification: Suggestive Harm (Copyright - Plagiarism)

        Post 4:
        "Everyone should just end it all. Life is meaningless. #Suicide"
        Classification: Immediate Harm (Violence - Self-Harm)

        Post 5:
        "This is what they don’t want you to see! [edited video] #Conspiracy"
        Classification: Suggestive Harm (Misleading - Manipulated Media - Edited)

        Post 6:
        "You're such a loser, no one likes you. Just disappear. #Bullying"
        Classification: Immediate Harm (Harassment - Bullying)

        Post 7:
        "This group of people is ruining our country. We need to get rid of them. #HateSpeech"
        Classification: Immediate Harm (Inflammatory - Hate Speech)

        Post: {post}
        
        Answer using the following format:
        Classification: THIS POST IS A SUGGESTIVE HARM
        Explanation: [Your explanation here]"""

        return PROMPT.format(post=post)      
    
    async def is_immediate_harm(self, report):
        # Use OpenAI to classify the content
        client = OpenAI(api_key=openai_api_key)
        response_4o = client.chat.completions.create(
            # temperature
            # The temperature of the sampling distribution. Must be strictly positive.
            temperature=0.0,
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "Your job is to classify the following post based on its content. Determine whether it falls under 'immediate harm' or 'suggestive harm' according to the criteria outlined in the Reporting Guide. Use the definitions below to make your classification:",
                },
                {"role": "user", "content": self.generate_prompt(report.message.content)},
            ],
        ).choices[0].message.content

        client = discovery.build(
            "commentanalyzer",
            "v1alpha1",
            developerKey=perspective_api_key,
            discoveryServiceUrl="https://commentanalyzer.googleapis.com/$discovery/rest?version=v1alpha1",
            static_discovery=False,
        )

        analyze_request = {
            'comment': { 'text': 'friendly greetings from python' },
            'requestedAttributes': {'TOXICITY': {}}
        }

        response_pers = client.comments().analyze(body=analyze_request).execute()
        perspective_score = response_pers["attributeScores"]["TOXICITY"]["summaryScore"]["value"]

        classification = re.search(r'Classification: (.+)', response_4o).group(1)
        explanation = re.search(r'Explanation: (.+)', response_4o).group(1)


        report.moderator_4o_category = classification
        report.moderator_4o_decision_explanation = explanation
        report.moderator_perspective_score = perspective_score

        if report.category == 'Violence':
            is_immediate_harm = 'immediate' in classification.lower()
        else:
            is_immediate_harm = 'immediate' in classification.lower() and perspective_score > 0.75

        mod_channel = self.mod_channels[self.guild_id]
        sysmsg = f'===== Immediate Harm Report =====\n'
        sysmsg += f'- Category: `{report.category}`\n'
        sysmsg += f'- Sub-category: `{report.sub_category}`\n'
        if report.sub_sub_category is not None:
            sysmsg += f'- Clarifying category: `{report.sub_sub_category}`\n'
        sysmsg += f'- Content: "{report.message.content}"\n'
        sysmsg += f'- Explanation: "{report.moderator_decision_explanation}"\n'
        sysmsg += f'- Perspective Toxicity score: "{report.moderator_perspective_score}"\n'
        await mod_channel.send(sysmsg)

        return is_immediate_harm
            

    async def handle_report(self):
        '''
        A background task to handle report queue.
        '''
        await self.wait_until_ready()
        while not self.is_closed():
            # If the mod channel is set up and we have at least one report in the queue,
            # start the review process
            if self.mod_channels and self.report_queue:
                # Retreive the report

                sybilrank_score, _, report = heapq.heappop(self.report_queue)
                
                if report is not None:
                    immediate_harm = await self.is_immediate_harm(report)

                if report is None:
                    # If it's a dummy report, do nothing
                    await asyncio.sleep(20)
                elif immediate_harm:
                    # Handle immediate harm
                    await self.handle_immediate_harm(report)
                else:
                    # Initiate appeal process
                    # TODO: Move this into a new method and complete the process
                    appeal_thread = await report.message.channel.create_thread(name="appeal process", invitable=False)
                    await appeal_thread.add_user(report.message.author)
                    message = report.message
                    await appeal_thread.send(
                        f'Your post on `{message.created_at:%m/%d/%Y}` has been reported for being `{report.category}`. ' +
                        'This is a violation of Facebook\'s Community Guideline. Please take down or edit your post ' +
                        'within the next 24 hours to avoid internal processing of the report.\n' +
                        'If you belive this report is a mistake, please begin an appeal process.'
                    )
                    await appeal_thread.send("Submit your appeal here:")
                    self.suggestive_harm_dict[appeal_thread.id] = (appeal_thread, report)
            # Otherwise, sleep for 10 seconds
            else:
                await asyncio.sleep(10)


    async def handle_immediate_harm(self, report):
        # Immediately remove content that are considered immediate harm.
        message = report.message
        violation_type = f'`{report.category}`'
        if report.category == 'Sexual':
            violation_type = 'being ' + violation_type
        await report.message.author.send(
            f'Your post on `{message.created_at:%m/%d/%Y}` has been reported for {violation_type}. ' +
            'This is a violation of Facebook\'s Community Guideline.\n' +
            'We have decided to take down the content. Thanks for your understanding.'
        )
        await report.message.delete()
        sysmsg += 'Our system has decided that this content must be removed. '
        sysmsg += 'The post is deleted, and a warning is issued to the author.'
        await mod_channel.send(sysmsg)


    async def handle_appeal(self, message):
        # Retrieve the related report and appeal thread
        thread, report = self.suggestive_harm_dict[message.channel.id]
        # Send everyting to the mod channel
        mod_channel = self.mod_channels[message.guild.id]
        sysmsg = f'===== Suggestive Harm Report =====\n'
        sysmsg += f'- ID: `{message.channel.id}`\n'
        sysmsg += f'- Category: `{report.category}`\n'
        sysmsg += f'- Sub-category: `{report.sub_category}`\n'
        if report.sub_sub_category is not None:
            sysmsg += f'- Clarifying category: `{report.sub_sub_category}`\n'
        sysmsg += f'- Content: "{report.message.content}"\n'
        sysmsg += f'- Report description: "{report.report_description}"\n'
        sysmsg += f'- Appeal: "{message.content}"\n'
        sysmsg += '=============================\n'
        sysmsg += 'React to this message with:\n'
        sysmsg += '- 🟢 (keep the content)\n'
        sysmsg += '- 🔴 (remove the content)'
        await mod_channel.send(sysmsg)


    async def on_reaction_add(self, reaction, user):
        # Only handle reactions to manual review
        if reaction.message.channel.name != f'group-{self.group_num}-mod':
            return
        if not re.search('Suggestive Harm Report', reaction.message.content):
            return
        
        # Parse the appeal thread id and retrieve the report and thread
        m = re.search('ID: `.*`', reaction.message.content)
        thread_id = int(m.group(0)[5:-1])
        thread, report = self.suggestive_harm_dict.pop(thread_id)

        # Take actions based on the reaction
        if str(reaction.emoji) == '🟢':
            await thread.send(
                'We have reviewed your appeal and decided to keep your content.\n' +
                'This thread will be closed soon. Thanks for your patience.'
            )
        elif str(reaction.emoji) == '🔴':
            await report.message.delete()
            await thread.send(
                'We have reviewed your appeal and decided to remove your content.\n' +
                'This thread will be closed soon. Thanks for your understanding.'
            )
        
        # Sleep for 10 seconds and then close the appeal thread
        await asyncio.sleep(10)
        await thread.delete()


    async def handle_channel_message(self, message):
        # Only handle messages sent in the "group-#" channel
        if not message.channel.name == f'group-{self.group_num}':
            return

        # Forward the message to the mod channel
        mod_channel = self.mod_channels[message.guild.id]
        await mod_channel.send(f'Forwarded message:\n{message.author.name}: "{message.content}"')
        scores = self.eval_text(message.content)
        await mod_channel.send(self.code_format(scores))

    
    def eval_text(self, message):
        ''''
        TODO: Once you know how you want to evaluate messages in your channel, 
        insert your code here! This will primarily be used in Milestone 3. 
        '''
        return message

    
    def code_format(self, text):
        ''''
        TODO: Once you know how you want to show that a message has been 
        evaluated, insert your code here for formatting the string to be 
        shown in the mod channel. 
        '''
        return "Evaluated: '" + text+ "'"


client = ModBot()
client.run(discord_token)