# Fairprice telegram bot

A lightweight Telegram bot for querying grocery prices and managing local shopping data in Singapore.

Disclaimer: This repository is not endorsed by NTUC, Fairprice Group or its associates. This is purely a personal project. Use at your own risk.

Features
- Telegram bot that handles inline queries
- Query FairPrice product prices 

## Using the bot
Use the bot via Telegram at @ddonobot (or your own bot username after setup, if you are self hosting).

Commands:
- `/start` — bot welcome message
- `/help` — usage instructions
- `/display`, `/remove`, `/clear` — grocery list management

## Quick start (local)
This section is only relevant if you want to run this bot on your own server.

1. Create Python venv:
   - `python3 -m venv .venv`
   - `source .venv/bin/activate`
2. Install deps: `pip install -r requirements.txt`
3. Put bot token in `bot_token.txt` or set an environment variable BOT_TOKEN
4. Run: `python main.py`

## Telegram bot setup (@BotFather)
1. Create your bot with BotFather:
   - Open Telegram and chat with @BotFather
   - Use `/newbot`, set a name and username
   - Copy your API token
2. For full setup and commands, see Telegram docs:
   - https://core.telegram.org/bots#6-botfather

## Docker setup

1. Build image:
   - `docker build -t fairprice-telebot .`
2. Run container:
   - `touch bot_token.txt`
   - Paste your bot token inside `bot_token.txt`
   - `docker run -d --name telebot -v "$PWD/bot_token.txt":/app/bot_token.txt fairprice-telebot`
   
   or if you prefer using an environment variable
   - `touch .env`
   - Set the BOT_TOKEN variable (without quotes, for e.g BOT_TOKEN=this_is_a_token)
   - `docker run -d --name telebot --env-file .env fairprice-telebot`

## Notes
- If using persistent state (e.g., `GM.db`), mount volume:
  `-v "$PWD/GM.db":/app/GM.db`

