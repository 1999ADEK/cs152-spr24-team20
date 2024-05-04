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
from collections import deque

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
        if message.guild:
            await self.handle_channel_message(message)
        else:
            await self.handle_dm(message)

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
        # TODO: There might be a bug in current Report implementation
        #       I need to send an extra dm message to the bot to get to this part of the code
        if self.reports[author_id].report_complete():
            report = self.reports.pop(author_id)
            # If the report is cancelled, do nothing
            if report.category is None or report.sub_category is None:
                return
            # Otherwise, start the moderating process
            if report.category in ["Harassment"]: # Immediate harms
                # Handle algorithmic review process
                self.immediate_harm_queue.append(report)
            elif report.category in ["Spam", "Misinformation"]: # Suggestive harms
                # Handle appeal process
                # TODO: Create another method and complete the process
                await self.mod_channels[self.guild_id].send(
                    f'Got a report. Category: {report.category} | Sub-category: {report.sub_category}\n' + 
                    f'TODO: Handle the appeal process via DM.'
                )
            else:
                raise ValueError(f"Found undefined category {report.category}.")
            

    async def handle_immediate_harm(self):
        '''
        A background task to handle immediate harm reports.
        '''
        await self.wait_until_ready()
        while not self.is_closed():
            # If the mod channel is set up and we have at least one immediate harm in the queue,
            # start the review process
            # TODO: Complete the process
            if self.mod_channels and self.immediate_harm_queue:
                report = self.immediate_harm_queue.popleft()
                mod_channel = self.mod_channels[self.guild_id]
                await mod_channel.send(
                    f'Got a report. Category: {report.category} | Sub-category: {report.sub_category}'
                )
            # Otherwise, sleep for 30 seconds
            else:
                await asyncio.sleep(30)


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