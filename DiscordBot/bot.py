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
from collections import deque, OrderedDict

# Set up logging to the console
logger = logging.getLogger('discord')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

# There should be a file called 'tokens.json' inside the same folder as this file
token_path = 'tokens.json'
if not os.path.isfile(token_path):
    raise Exception(f"{token_path} not found!")
with open(token_path) as f:
    # If you get an error here, it means your token is formatted incorrectly. Did you put it in quotes?
    tokens = json.load(f)
    discord_token = tokens['discord']


class ModBot(discord.Client):
    def __init__(self): 
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='.', intents=intents)
        self.group_num = None
        self.mod_channels = {} # Map from guild to the mod channel id for that guild
        self.reports = {} # Map from user IDs to the state of their report

        # A queue to handle reports of immediate harms
        # TODO: Probably have to switch to heap to support SybilRank priority
        self.immediate_harm_queue = deque()
        # A queue to handle reports of suggestive harms
        self.suggestive_harm_dict = OrderedDict()

    async def setup_hook(self):
        '''
        Setup a background task.
        '''
        self.bg_task = self.loop.create_task(self.handle_immediate_harm())
    
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
            # Otherwise, start the moderating process
            if self.is_immediate_harm(report):
                # Handle algorithmic review process
                self.immediate_harm_queue.append(report)
            else:
                # Handle appeal process
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
            
    
    def is_immediate_harm(self, report):
        '''
        An algorithm to decide whether the reported content is immediate harm.
        '''
        # TODO: In milstone 3 this should be a ML model
        # Here we just simply decide the harm type based on categories
        if report.sub_sub_category in [
            "Recruitment", "Promotion", "Suicidal", "Promotion", "Drug Abuse",
            "Personal Attacks", "Cyberstalking", "Targetting", "Grooming", "Physical Abuse", "Emotional Abuse"
        ]:
            return True
        elif report.sub_category in [
            "Threats", "Glorification", "Graphic", "Explicit Sexual Activity", "Explicit Text", "Sexual Violence",
            "Plagiarism", "Defamation", "Counterfeit", "Privacy Issues", "Scams", "Hate Speech"
        ]:
            return True
        else:
            return False
            

    async def handle_immediate_harm(self):
        '''
        A background task to handle immediate harm reports.
        '''
        await self.wait_until_ready()
        while not self.is_closed():
            # If the mod channel is set up and we have at least one immediate harm in the queue,
            # start the review process
            # TODO: In milestone 3 we need to implement an algortihm to decide whether
            #       to remove the content
            if self.mod_channels and self.immediate_harm_queue:
                # Retreive the report
                report = self.immediate_harm_queue.popleft()
                # Delete the message and send a warning to the author
                await report.message.delete()
                await report.message.author.send(
                    'TODO: Edit the warning message sent to the author here.'
                )
                # Record the review result in the mod channel
                mod_channel = self.mod_channels[self.guild_id]
                await mod_channel.send(
                    f'=====Immediate Harm Report=====\n' +
                    f'Category: {report.category} | Sub-category: {report.sub_category}\n' +
                    f'Content: "{report.message.content}"\n' +
                    f'Our system has decided that this content must be removed. ' +
                    f'The message is deleted, and a warning is issued to the author.'
                )
            # Otherwise, sleep for 30 seconds
            else:
                await asyncio.sleep(30)


    async def handle_appeal(self, message):
        # Retrieve the related report and appeal thread
        thread, report = self.suggestive_harm_dict[message.channel.id]
        # Send everyting to the mod channel
        mod_channel = self.mod_channels[message.guild.id]
        await mod_channel.send(
            f'===Manual review===\n' +
            f'ID: `{message.channel.id}`\n' +
            f'Message to review:\n"{report.message.content}"\n' +
            f'Appeal:\n"{message.content}"\n' +
            f'React to this message with:\n' +
            f'- 🟢 (keep the content)\n' +
            f'- 🔴 (remove the content)'
        )


    async def on_reaction_add(self, reaction, user):
        # Only handle reactions to manual review
        if reaction.message.channel.name != f'group-{self.group_num}-mod':
            return
        if not re.search('Manual review', reaction.message.content):
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