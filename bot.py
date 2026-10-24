import os, re, json, asyncio, sqlite3, logging
from datetime import datetime, timezone, timedelta
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
import praw

load_dotenv()
TOKEN=os.getenv("DISCORD_TOKEN","").strip()
GUILD_ID=os.getenv("GUILD_ID","").strip()
CID=os.getenv("REDDIT_CLIENT_ID","").strip()
CSECRET=os.getenv("REDDIT_CLIENT_SECRET","").strip()
UA=os.getenv("REDDIT_USER_AGENT","windows:discord-autopost:v1.0 (by u/YourRedditUsername)")
DB=os.getenv("DB_PATH","autopost.sqlite3")
LAYOUT=os.getenv("TEMPLATE_PATH","layout.json")
DEFAULT_INTERVAL=os.getenv("DEFAULT_INTERVAL","5m")
DEFAULT_LIMIT=int(os.getenv("DEFAULT_POST_LIMIT","10"))
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log=logging.getLogger("autopost")
bot=commands.Bot(command_prefix="!",intents=discord.Intents.default())
reddit=None
layout=[]

def init_db():
    with sqlite3.connect(DB) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS feeds(
        id INTEGER PRIMARY KEY AUTOINCREMENT,guild TEXT,channel TEXT,subreddit TEXT,
        interval INTEGER,limit_count INTEGER,posted INTEGER DEFAULT 0,active INTEGER DEFAULT 1,next_run TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS sent(id TEXT PRIMARY KEY,feed_id INTEGER,at TEXT)""")
        c.commit()

def q(sql,args=(),fetch=False):
    with sqlite3.connect(DB) as c:
        cur=c.execute(sql,args); rows=cur.fetchall() if fetch else None; c.commit(); return rows

def getreddit():
    global reddit
    if reddit is None:
        if not CID or not CSECRET: raise RuntimeError("Add Reddit API credentials to .env.")
        reddit=praw.Reddit(client_id=CID,client_secret=CSECRET,user_agent=UA,ratelimit_seconds=10)
        reddit.read_only=True
    return reddit

def parse_interval(s):
    m=re.fullmatch(r"\s*(\d+)\s*([smhd])\s*",s or "",re.I)
    if not m: raise ValueError("Use 30s, 3m, 5h, or 1d.")
    n=int(m.group(1)); sec=n*{"s":1,"m":60,"h":3600,"d":86400}[m.group(2).lower()]
    if sec<30: raise ValueError("Minimum interval is 30 seconds to reduce spam and respect rate limits.")
    return sec

def fmt(sec):
    for u,n in (("d",86400),("h",3600),("m",60),("s",1)):
        if sec%n==0:return f"{sec//n}{u}"
    return f"{sec}s"

def adult_name(n):
    return any(x in n.casefold() for x in ("nsfw","porn","hentai","onlyfans","boobs","ass","bdsm","femboy","milf","dilf","thirst","lesbian","gay","yaoi","yuri"))

def get_layout():
    with open(LAYOUT,encoding="utf-8") as f:return json.load(f)

def embed_for(s,feed):
    e=discord.Embed(title=(s.title[:250] or "(untitled post)"),url="https://www.reddit.com"+s.permalink,
      description=f"Source: r/{s.subreddit.display_name}",timestamp=datetime.fromtimestamp(s.created_utc,tz=timezone.utc),color=discord.Color.orange())
    e.add_field(name="Feed",value=feed[:100],inline=True)
    e.add_field(name="Score",value=str(s.score),inline=True)
    e.add_field(name="Comments",value=str(s.num_comments),inline=True)
    kind="Video" if getattr(s,"is_video",False) else "Gallery" if getattr(s,"is_gallery",False) else "Image" if getattr(s,"post_hint","")=="image" else "Reddit post"
    e.add_field(name="Type",value=kind,inline=True)
    e.set_footer(text="Reddit • Open the post to view media and comments")
    return e

async def newest(subreddit,limit=10):
    r=getreddit()
    return await asyncio.to_thread(lambda:list(r.subreddit(subreddit).new(limit=limit)))

async def send_post(ch,s,feed_id,feed_label):
    if getattr(s,"over_18",False) and not ch.is_nsfw():
        log.warning("Blocked age-restricted post in #%s",ch.name); return False
    if q("SELECT 1 FROM sent WHERE id=?",(s.id,),True): return False
    await ch.send(embed=embed_for(s,feed_label),allowed_mentions=discord.AllowedMentions.none())
    q("INSERT OR IGNORE INTO sent(id,feed_id,at) VALUES(?,?,?)",(s.id,feed_id,datetime.now(timezone.utc).isoformat()))
    return True

def active(guild=None,channel=None):
    sql="SELECT id,guild,channel,subreddit,interval,limit_count,posted,next_run FROM feeds WHERE active=1"; a=[]
    if guild is not None: sql+=" AND guild=?"; a.append(str(guild))
    if channel is not None: sql+=" AND channel=?"; a.append(str(channel))
    return q(sql+" ORDER BY id",tuple(a),True) or []

@tasks.loop(seconds=15)
async def scheduler():
    now=datetime.now(timezone.utc)
    for row in active():
        fid,gid,cid,sr,interval,limit_count,posted,next_run=row
        if datetime.fromisoformat(next_run)>now: continue
        try:
            guild=bot.get_guild(int(gid)); ch=guild.get_channel(int(cid)) if guild else None
            if not isinstance(ch,discord.TextChannel): continue
            if limit_count is not None and posted>=limit_count:
                q("UPDATE feeds SET active=0 WHERE id=?",(fid,)); continue
            posts=await newest(sr,10); sent=0
            for s in reversed(posts):
                if limit_count is not None and posted+sent>=limit_count: break
                if await send_post(ch,s,fid,"r/"+sr):
                    sent+=1; await asyncio.sleep(1)
            newcount=posted+sent
            if limit_count is not None and newcount>=limit_count:
                q("UPDATE feeds SET posted=?,active=0 WHERE id=?",(newcount,fid))
            else:
                nxt=(datetime.now(timezone.utc)+timedelta(seconds=interval)).isoformat()
                q("UPDATE feeds SET posted=?,next_run=? WHERE id=?",(newcount,nxt,fid))
            await asyncio.sleep(2)
        except Exception as e: log.warning("Feed #%s failed: %s",fid,e)

@scheduler.before_loop
async def wait_ready(): await bot.wait_until_ready()

def manager(i): return bool(i.guild and i.user.guild_permissions.manage_channels)

@bot.event
async def on_ready():
    global layout
    log.info("Logged in as %s",bot.user)
    if not layout: layout=get_layout()
    init_db()
    try:
        if GUILD_ID:
            g=discord.Object(id=int(GUILD_ID)); bot.tree.copy_global_to(guild=g); synced=await bot.tree.sync(guild=g)
        else: synced=await bot.tree.sync()
        log.info("Synced %s slash commands",len(synced))
    except Exception: log.exception("Command sync failed")
    if not scheduler.is_running(): scheduler.start()

@bot.tree.command(name="autopost_start",description="Start a subreddit feed in this channel")
@app_commands.describe(subreddit="Public subreddit name without r/",interval="30s, 3m, 5h, or 1d",times="Posts before stopping; 0 means unlimited")
async def autopost_start(i:discord.Interaction,subreddit:str,interval:str=DEFAULT_INTERVAL,times:app_commands.Range[int,0,500]=DEFAULT_LIMIT):
    if not i.guild or not isinstance(i.channel,discord.TextChannel): await i.response.send_message("Use this in a server text channel.",ephemeral=True); return
    if not manager(i): await i.response.send_message("You need Manage Channels permission.",ephemeral=True); return
    if adult_name(i.channel.name) and not i.channel.is_nsfw():
        await i.response.send_message("This looks like an adult channel, but Discord does not mark it age-restricted. Enable Age-Restricted Channel in channel settings first.",ephemeral=True); return
    try: seconds=parse_interval(interval)
    except ValueError as e: await i.response.send_message(str(e),ephemeral=True); return
    await i.response.defer(ephemeral=True,thinking=True)
    try: await newest(subreddit,1)
    except Exception as e: await i.followup.send(f"Couldn't access r/{subreddit}: {type(e).__name__}. Check subreddit name/API credentials.",ephemeral=True); return
    lim=None if times==0 else int(times); now=datetime.now(timezone.utc)
    q("INSERT INTO feeds(guild,channel,subreddit,interval,limit_count,posted,active,next_run) VALUES(?,?,?,?,?,0,1,?)",
      (str(i.guild.id),str(i.channel.id),subreddit.strip(),seconds,lim,(now+timedelta(seconds=seconds)).isoformat()))
    rows=q("SELECT id FROM feeds WHERE guild=? AND channel=? ORDER BY id DESC LIMIT 1",(str(i.guild.id),str(i.channel.id)),True)
    await i.followup.send(f"Started feed **#{rows[0][0]}** in {i.channel.mention} from **r/{subreddit}**. Interval: **{fmt(seconds)}**; limit: **{'unlimited' if lim is None else lim}**.",ephemeral=True)

@bot.tree.command(name="autopost_custom",description="Set up a custom subreddit feed in this channel")
@app_commands.describe(subreddit="Subreddit name without r/",interval="30s, 3m, 5h, or 1d",times="Posts before stopping; 0 means unlimited")
async def autopost_custom(i:discord.Interaction,subreddit:str,interval:str=DEFAULT_INTERVAL,times:app_commands.Range[int,0,500]=DEFAULT_LIMIT):
    await autopost_start.callback(i,subreddit,interval,times)

@bot.tree.command(name="autopost_stop",description="List active feeds in this channel")
async def autopost_stop(i:discord.Interaction):
    if not i.guild or not isinstance(i.channel,discord.TextChannel): await i.response.send_message("Use this in a server text channel.",ephemeral=True); return
    if not manager(i): await i.response.send_message("You need Manage Channels permission.",ephemeral=True); return
    rows=active(i.guild.id,i.channel.id)
    if not rows: await i.response.send_message("No active feeds in this channel.",ephemeral=True); return
    msg="\n".join(f"**#{r[0]}** · r/{r[3]} · every {fmt(r[4])} · {r[6]}/{r[5] if r[5] is not None else '∞'} posts" for r in rows)
    await i.response.send_message(msg+"\nStop one with `/autopost_stop_id feed_id`.",ephemeral=True)

@bot.tree.command(name="autopost_stop_id",description="Stop an autopost by ID")
async def autopost_stop_id(i:discord.Interaction,feed_id:int):
    if not i.guild or not isinstance(i.channel,discord.TextChannel) or not manager(i):
        await i.response.send_message("Use in a server channel with Manage Channels permission.",ephemeral=True); return
    found=q("SELECT id FROM feeds WHERE id=? AND guild=? AND channel=? AND active=1",(feed_id,str(i.guild.id),str(i.channel.id)),True)
    if not found: await i.response.send_message("Active feed not found in this channel.",ephemeral=True); return
    q("UPDATE feeds SET active=0 WHERE id=?",(feed_id,))
    await i.response.send_message(f"Stopped feed **#{feed_id}**.",ephemeral=True)

@bot.tree.command(name="configure_channel",description="Check or set this channel's age-restricted setting")
@app_commands.describe(age_restricted="Set true to mark age-restricted, false to turn it off")
async def configure_channel(i:discord.Interaction,age_restricted:bool=None):
    if not i.guild or not isinstance(i.channel,discord.TextChannel) or not manager(i):
        await i.response.send_message("Use in a server text channel with Manage Channels permission.",ephemeral=True); return
    if age_restricted is None:
        await i.response.send_message(f"{i.channel.mention} age-restricted: **{i.channel.is_nsfw()}**. Run `/configure_channel age_restricted:true` to enable.",ephemeral=True); return
    try:
        await i.channel.edit(nsfw=age_restricted,reason="Channel feed configuration")
        await i.response.send_message(f"Age-restricted setting is now **{age_restricted}**.",ephemeral=True)
    except discord.Forbidden: await i.response.send_message("Bot lacks permission to edit this channel.",ephemeral=True)

@bot.tree.command(name="autopost_list",description="List active autopost feeds in this server")
async def autopost_list(i:discord.Interaction):
    if not i.guild or not manager(i): await i.response.send_message("You need Manage Channels permission.",ephemeral=True); return
    rows=active(i.guild.id)
    if not rows: await i.response.send_message("No active feeds.",ephemeral=True); return
    await i.response.send_message("\n".join(f"**#{r[0]}** <#{r[2]}> · r/{r[3]} · {fmt(r[4])} · {r[6]}/{r[5] if r[5] is not None else '∞'}" for r in rows[:30]),ephemeral=True)

if not TOKEN: raise RuntimeError("Missing DISCORD_TOKEN in .env")
if not CID or not CSECRET: log.warning("Reddit API credentials missing; feed commands will fail until configured.")
bot.run(TOKEN)
