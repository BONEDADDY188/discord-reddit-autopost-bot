# Booty-style Reddit Autopost Bot

Independent implementation of the workflow shown in your screenshots; it is not Booty Bot's code and does not include its premium-only service.

## Commands
- `/autopost_start subreddit interval times` — start a subreddit feed in the current channel.
- `/autopost_custom subreddit interval times` — custom subreddit feed.
- `/autopost_stop` — list feeds running in this channel.
- `/autopost_stop_id feed_id` — stop one feed.
- `/configure_channel` — check age restriction; set `age_restricted:true` or `false`.
- `/autopost_list` — list active feeds across the server.

Intervals accept `30s`, `3m`, `5h`, `1d`. Minimum is 30 seconds to avoid rapid-fire posting. `times=0` means unlimited; otherwise the feed stops after that many posts. Feed state and deduplication persist in SQLite.

## Windows setup
1. Stop the old bot with Ctrl+C and extract this ZIP into a new folder.
2. In PowerShell in that folder run:
   `py -3.13 -m pip install -r requirements.txt`
   `Copy-Item .env.example .env`
   `notepad .env`
3. Add your Discord token and Reddit API credentials:
   - `DISCORD_TOKEN`
   - `GUILD_ID` (recommended: your server ID, so slash commands sync quickly)
   - `REDDIT_CLIENT_ID`
   - `REDDIT_CLIENT_SECRET`
   - `REDDIT_USER_AGENT` (identify your app and Reddit username)
4. Start with `py -3.13 bot.py`.
5. In each destination channel run `/autopost_start`, then enter the public subreddit name, interval, and post count.

## Reddit API
This bot uses PRAW to read Reddit's public `new` listings through authorized API access. It does not scrape pages or bypass access controls. API credentials and approval may be required under Reddit's current policies:
https://support.reddithelp.com/hc/en-us/articles/14945211791892-Developer-Platform-Accessing-Reddit-Data
https://www.reddit.com/dev/api/

## Adult content and limits
- The 17 channels from your screenshot are included in `layout.json`; existing Discord channels must actually be age-restricted in Discord.
- Reddit posts flagged `over_18` are blocked from channels that Discord does not mark age-restricted. Reddit flags are imperfect; moderation remains your responsibility.
- The bot posts links and metadata, not downloaded/rehosted media.
- Reddit/Discord rate limits apply. The minimum interval is 30 seconds and messages are paced.
- Make sure you have authority to manage the server, and follow Reddit's API terms, subreddit rules, Discord policies, and applicable age restrictions.
