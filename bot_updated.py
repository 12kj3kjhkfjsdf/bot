import discord
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput
import json
import os
import random
import time
import asyncio
import re
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta


# ============================================================
# CONFIGURATION
# ============================================================

TOKEN = os.getenv("DISCORD_TOKEN", "PASTE_YOUR_BOT_TOKEN_HERE")

PREFIX = "!"

ADMIN_ROLE_NAME = "Admin"
TICKET_MANAGER_ROLE_NAME = "Ticket manager"
SPAWNER_STAFF_ROLE_NAME = "Spawner Staff"
BUILDER_ROLE_NAMES = ("Digger", "Builders")

# These two roles are ALWAYS pinged on new tickets.
ALWAYS_PING_ROLE_IDS = (
    1492159355620167720,
    1352631033484546090,
)

TICKET_CATEGORY_NAME = "Tickets"
SERVICE_CATEGORY_NAME = "Service Tickets"

TRANSCRIPT_CHANNEL_NAME = "ticket-transcripts"
LOW_STOCK_CHANNEL_NAME = "shop-alerts"

MINIMUM_BUY = 10
TICKET_COOLDOWN = 300
LOW_STOCK_LIMIT = 10


# ============================================================
# DEFAULT PRICES
# ============================================================

DEFAULT_BUY_PRICES = {
    "Skeleton": 7_000_000,
    "Iron Golem": 18_000_000,
    "Creeper": 16_000_000,
}

DEFAULT_SELL_PRICES = {
    "Skeleton": 5_000_000,
    "Iron Golem": 14_000_000,
    "Creeper": 12_000_000,
}

DEFAULT_STOCK = {
    "Skeleton": 0,
    "Iron Golem": 0,
    "Creeper": 0,
}


# ============================================================
# SERVICES
# ============================================================

SERVICES = {
    "Low Cords": "15M",
    "Mid Cords": "25M",
    "Good Cords": "40M",
    "God Cords": "50M",
    "Digging": "Negotiable",
    "Base Building": "Negotiable",
}


# ============================================================
# JSON FILES
# ============================================================

PRICES_FILE = "prices.json"
STOCK_FILE = "stock.json"
COOLDOWNS_FILE = "cooldowns.json"
DEALS_FILE = "deals.json"

PAYMENTS_FILE = "payments.json"
PAYMENT_HISTORY_FILE = "payment_history.json"

ORDERS_FILE = "orders.json"
REVIEWS_FILE = "reviews.json"
ADMIN_STATS_FILE = "admin_stats.json"

AFK_FILE = "afk.json"
IGN_FILE = "igns.json"


# ============================================================
# JSON HELPERS
# ============================================================

def load_json(filename, default):
    if not os.path.exists(filename):
        return default

    try:
        with open(filename, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return default


def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)


# ============================================================
# LOAD DATA
# ============================================================

price_data = load_json(
    PRICES_FILE,
    {
        "buy": DEFAULT_BUY_PRICES.copy(),
        "sell": DEFAULT_SELL_PRICES.copy(),
    },
)

buy_prices = price_data.get("buy", DEFAULT_BUY_PRICES.copy())
sell_prices = price_data.get("sell", DEFAULT_SELL_PRICES.copy())

stock = load_json(STOCK_FILE, DEFAULT_STOCK.copy())
cooldowns = load_json(COOLDOWNS_FILE, {})
deals = load_json(DEALS_FILE, {})

payments = load_json(PAYMENTS_FILE, {})
payment_history = load_json(PAYMENT_HISTORY_FILE, [])

orders = load_json(ORDERS_FILE, {})
reviews = load_json(REVIEWS_FILE, [])

admin_stats = load_json(ADMIN_STATS_FILE, {})
afk_admins = load_json(AFK_FILE, {})
igns = load_json(IGN_FILE, {})


# ============================================================
# DISCORD SETUP
# ============================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None,
    case_insensitive=True,
)
# ============================================================
# MODERATION / ANTI-SPAM
# ============================================================

SPAM_MESSAGE_LIMIT = 10
SPAM_WINDOW_SECONDS = 10
SPAM_FIRST_TIMEOUT_SECONDS = 60
SPAM_SECOND_TIMEOUT_SECONDS = 2 * 60 * 60
SPAM_ESCALATION_WINDOW_SECONDS = 60 * 60

spam_message_times = defaultdict(deque)
spam_escalation = {}


# ============================================================
# BASIC HELPERS
# ============================================================

def money(value):
    return f"{int(value):,}"


def format_amount(value):
    value = int(value)

    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:g}B"

    if value >= 1_000_000:
        return f"{value / 1_000_000:g}M"

    if value >= 1_000:
        return f"{value / 1_000:g}K"

    return str(value)


def parse_amount(value):
    if isinstance(value, (int, float)):
        return int(value)

    value = str(value).strip().lower().replace(",", "")

    try:
        if value.endswith("k"):
            return int(float(value[:-1]) * 1_000)

        if value.endswith("m"):
            return int(float(value[:-1]) * 1_000_000)

        if value.endswith("b"):
            return int(float(value[:-1]) * 1_000_000_000)

        return int(float(value))

    except ValueError:
        return None


def clean_channel_name(value):
    value = value.lower()
    value = re.sub(r"[^a-z0-9-]", "-", value)
    value = re.sub(r"-+", "-", value)
    value = value.strip("-")

    return value[:90]


def normalize_spawner(value):
    value = str(value).lower().strip()

    aliases = {
        "skelly": "Skeleton",
        "skeleton": "Skeleton",
        "skeletons": "Skeleton",

        "ig": "Iron Golem",
        "iron": "Iron Golem",
        "irongolem": "Iron Golem",
        "iron golem": "Iron Golem",
        "iron golems": "Iron Golem",

        "creeper": "Creeper",
        "creepers": "Creeper",
    }

    return aliases.get(value)


def next_order_id():
    numbers = []

    for order_id in orders.keys():
        try:
            numbers.append(int(order_id))
        except ValueError:
            pass

    return str(max(numbers, default=1000) + 1)


def save_prices():
    save_json(
        PRICES_FILE,
        {
            "buy": buy_prices,
            "sell": sell_prices,
        },
    )


# ============================================================
# ADMIN SYSTEM
# ============================================================

def is_admin(member):
    if not isinstance(member, discord.Member):
        return False

    if member.guild_permissions.administrator:
        return True

    role = discord.utils.get(
        member.guild.roles,
        name=ADMIN_ROLE_NAME,
    )

    if role and role in member.roles:
        return True

    return False


async def require_admin(ctx):
    if not is_admin(ctx.author):
        await ctx.send(
            "❌ You need the **Admin** role or Administrator permissions to use this command.",
            delete_after=8,
        )
        return False

    return True


def get_admins(guild):
    admins = []

    role = discord.utils.get(
        guild.roles,
        name=ADMIN_ROLE_NAME,
    )

    if role:
        admins.extend(role.members)

    for member in guild.members:
        if member.guild_permissions.administrator:
            if member not in admins:
                admins.append(member)

    return admins


def get_available_admins(guild):
    return [
        admin
        for admin in get_admins(guild)
        if str(admin.id) not in afk_admins
    ]


def get_role_by_name(guild, role_name):
    return discord.utils.find(
        lambda role: role.name.lower() == role_name.lower(),
        guild.roles,
    )


def is_ticket_manager(member):
    if not isinstance(member, discord.Member):
        return False

    role = get_role_by_name(
        member.guild,
        TICKET_MANAGER_ROLE_NAME,
    )
    return bool(role and role in member.roles)


async def require_ticket_manager(interaction):
    if is_ticket_manager(interaction.user):
        return True

    if interaction.response.is_done():
        return False

    await interaction.response.send_message(
        f"❌ Only the **{TICKET_MANAGER_ROLE_NAME}** role can use Claim, Priority, or Complete.",
        ephemeral=True,
    )
    return False


def ticket_staff_mentions(guild, ticket_type=None, service_name=None):
    mentions = []
    seen = set()

    def add_role(role):
        if role and role.id not in seen:
            seen.add(role.id)
            mentions.append(role.mention)

    for role_id in ALWAYS_PING_ROLE_IDS:
        role = guild.get_role(role_id)
        add_role(role)

    add_role(get_role_by_name(guild, TICKET_MANAGER_ROLE_NAME))

    if ticket_type == "spawner":
        add_role(get_role_by_name(guild, SPAWNER_STAFF_ROLE_NAME))

    if ticket_type == "service" and service_name in ("Base Building", "Digging"):

        for role_name in BUILDER_ROLE_NAMES:
            add_role(get_role_by_name(guild, role_name))

    return " ".join(mentions) or "No configured ticket staff roles found."


# ============================================================
# CATEGORIES
# ============================================================

def get_category(guild, name):
    return discord.utils.get(
        guild.categories,
        name=name,
    )


async def get_or_create_category(guild, name):
    category = get_category(guild, name)

    if category:
        return category

    return await guild.create_category(name)


# ============================================================
# TICKET DATA
# ============================================================

def get_ticket_data(channel):
    data = {}

    topic = channel.topic or ""

    for item in topic.split("|"):
        if "=" not in item:
            continue

        key, value = item.split("=", 1)
        data[key] = value

    return data


def set_ticket_data(channel, **updates):
    data = get_ticket_data(channel)

    for key, value in updates.items():
        data[key] = str(value).replace("|", "/")

    return "|".join(
        f"{key}={value}"
        for key, value in data.items()
    )


async def update_ticket_data(channel, **updates):
    topic = set_ticket_data(
        channel,
        **updates,
    )

    try:
        await channel.edit(topic=topic)
    except discord.HTTPException:
        pass


def ticket_owner(channel):
    data = get_ticket_data(channel)

    try:
        return int(data.get("user_id", 0))
    except ValueError:
        return None


def active_ticket_for_user(guild, user_id):
    categories = []

    ticket_category = get_category(
        guild,
        TICKET_CATEGORY_NAME,
    )

    if ticket_category:
        categories.append(ticket_category)

    service_category = get_category(
        guild,
        SERVICE_CATEGORY_NAME,
    )

    if service_category:
        categories.append(service_category)

    for category in categories:
        for channel in category.channels:

            if not isinstance(
                channel,
                discord.TextChannel,
            ):
                continue

            if ticket_owner(channel) == user_id:
                return channel

    return None


def is_ticket_channel(channel):
    if not isinstance(channel, discord.TextChannel):
        return False

    data = get_ticket_data(channel)

    return bool(
        data.get("type")
        and data.get("user_id")
        and data.get("order_id")
    )


# ============================================================
# DEAL SYSTEM
# ============================================================

def get_deal(spawner):
    deal = deals.get(spawner)

    if not deal:
        return None

    discount = int(
        deal.get("discount", 0)
    )

    return int(
        buy_prices[spawner]
        * (100 - discount)
        / 100
    )


def deal_text():
    if not deals:
        return "No active deals."

    lines = []

    for spawner, data in deals.items():

        if spawner not in buy_prices:
            continue

        discount = int(
            data.get("discount", 0)
        )

        original = buy_prices[spawner]

        discounted = int(
            original
            * (100 - discount)
            / 100
        )

        lines.append(
            f"🔥 **{spawner}** — "
            f"~~{format_amount(original)}~~ → "
            f"**{format_amount(discounted)}** "
            f"({discount}% OFF)"
        )

    return "\n".join(lines) or "No active deals."


# ============================================================
# SHOP EMBED
# ============================================================

def build_shop_embed():
    embed = discord.Embed(
        title="🛒 SPAWNER SHOP",
        description=(
            "Buy or sell Minecraft spawners using "
            "the buttons below.\n\n"
            f"📌 Minimum BUY amount: **{MINIMUM_BUY}**"
        ),
        color=discord.Color.green(),
    )

    for spawner in buy_prices:

        buy_price = buy_prices[spawner]
        sell_price = sell_prices.get(
            spawner,
            0,
        )

        current_stock = stock.get(
            spawner,
            0,
        )

        discounted = get_deal(spawner)

        if discounted:
            buy_display = (
                f"~~{format_amount(buy_price)}~~ "
                f"**{format_amount(discounted)}**"
            )
        else:
            buy_display = f"**{format_amount(buy_price)}**"

        if current_stock <= 0:
            stock_display = "🔴 OUT OF STOCK"

        elif current_stock <= LOW_STOCK_LIMIT:
            stock_display = (
                f"⚠️ LOW STOCK — {current_stock}"
            )

        else:
            stock_display = (
                f"🟢 {current_stock}"
            )

        embed.add_field(
            name=f"🟢 {spawner}",
            value=(
                f"💰 **Buy:** {buy_display}\n"
                f"💵 **Sell:** {format_amount(sell_price)}\n"
                f"📦 **Stock:** {stock_display}"
            ),
            inline=False,
        )

    if deals:
        embed.add_field(
            name="🔥 ACTIVE DEAL",
            value=deal_text(),
            inline=False,
        )

    embed.set_footer(
        text="Spawner Shop • Use the buttons to open a ticket"
    )

    return embed


# ============================================================
# SHOP PANEL UPDATE
# ============================================================

async def find_shop_message(guild):
    for channel in guild.text_channels:

        if channel.name not in (
            "shop",
            "spawner-shop",
        ):
            continue

        try:
            async for message in channel.history(
                limit=100
            ):

                if message.author.id != bot.user.id:
                    continue

                if not message.embeds:
                    continue

                if message.embeds[0].title == "🛒 SPAWNER SHOP":
                    return channel, message

        except Exception:
            pass

    return None, None


async def update_shop_panel(guild):
    channel, message = await find_shop_message(
        guild
    )

    if not message:
        return

    try:
        await message.edit(
            embed=build_shop_embed()
        )
    except discord.HTTPException:
        pass


# ============================================================
# LOW STOCK
# ============================================================

async def check_low_stock(guild, spawner):
    amount = stock.get(
        spawner,
        0,
    )

    if amount > LOW_STOCK_LIMIT:
        return

    channel = discord.utils.get(
        guild.text_channels,
        name=LOW_STOCK_CHANNEL_NAME,
    )

    if not channel:
        return

    if amount <= 0:

        await channel.send(
            f"🔴 **OUT OF STOCK**\n"
            f"**{spawner}** spawners are currently unavailable."
        )

    else:

        await channel.send(
            f"⚠️ **LOW STOCK**\n"
            f"**{spawner}:** {amount} remaining."
        )


# ============================================================
# ADMIN STATISTICS
# ============================================================

def add_admin_stat(
    admin,
    field,
    amount=1,
):
    key = str(admin.id)

    if key not in admin_stats:

        admin_stats[key] = {
            "name": str(admin),
            "tickets_completed": 0,
            "payments_handled": 0,
            "revenue_handled": 0,
            "reviews": [],
        }

    admin_stats[key]["name"] = str(admin)

    admin_stats[key][field] = (
        admin_stats[key].get(field, 0)
        + int(amount)
    )

    save_json(
        ADMIN_STATS_FILE,
        admin_stats,
    )


# ============================================================
# CREATE PERMISSIONS
# ============================================================

def build_ticket_overwrites(
    guild,
    customer,
):
    overwrites = {
        guild.default_role:
            discord.PermissionOverwrite(
                view_channel=False
            ),

        customer:
            discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            ),
    }

    staff_roles = []
    for role_name in (
        TICKET_MANAGER_ROLE_NAME,
        SPAWNER_STAFF_ROLE_NAME,
        *BUILDER_ROLE_NAMES,
    ):
        role = get_role_by_name(guild, role_name)
        if role and role not in staff_roles:
            staff_roles.append(role)

    for role in staff_roles:
        overwrites[role] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            manage_messages=True,
        )

    for admin in get_admins(guild):
        overwrites[admin] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            manage_messages=True,
        )

    return overwrites


async def refresh_ticket_scoreboard(channel, status_override=None):
    """Update the original ticket embed with live staff/status information."""
    if not isinstance(channel, discord.TextChannel):
        return

    data = get_ticket_data(channel)
    order_id = data.get("order_id", "Unknown")
    claimed_id = data.get("claimed_by", "")
    customer_id = data.get("user_id", "")
    completed = data.get("completed", "0") == "1"
    priority = data.get("priority", "0") == "1"

    claimed_member = None
    if claimed_id:
        try:
            claimed_member = channel.guild.get_member(int(claimed_id))
        except (TypeError, ValueError):
            pass

    customer = None
    if customer_id:
        try:
            customer = channel.guild.get_member(int(customer_id))
        except (TypeError, ValueError):
            pass

    if status_override:
        status = status_override
    elif completed:
        status = "COMPLETED"
    elif claimed_member:
        status = "CLAIMED"
    else:
        status = "OPEN"

    embed = discord.Embed(
        title="📋 TICKET SCOREBOARD",
        description=f"**Order:** #{order_id}",
        color=discord.Color.green() if status == "COMPLETED" else discord.Color.orange() if claimed_member else discord.Color.blue(),
    )
    embed.add_field(
        name="👤 Customer",
        value=customer.mention if customer else f"<@{customer_id}>" if customer_id else "Unknown",
        inline=True,
    )
    embed.add_field(
        name="🎮 In-game Name",
        value=f"`{igns.get(str(customer_id), 'Not assigned')}`" if customer_id else "Not assigned",
        inline=True,
    )
    embed.add_field(
        name="👑 Claimed By",
        value=claimed_member.mention if claimed_member else "Unclaimed",
        inline=True,
    )
    embed.add_field(
        name="📌 Priority",
        value="🚨 HIGH" if priority else "Normal",
        inline=True,
    )
    embed.add_field(
        name="📊 Status",
        value=status,
        inline=True,
    )

    # Do NOT include the spawner amount in the scoreboard after completion.
    if not completed and data.get("type") == "spawner":
        embed.add_field(
            name="📦 Spawner",
            value=data.get("spawner", "Unknown"),
            inline=True,
        )
        embed.add_field(
            name="🔢 Amount",
            value=data.get("amount", "0"),
            inline=True,
        )

    if data.get("type") == "service":
        embed.add_field(
            name="🛠️ Service",
            value=data.get("service", "Unknown"),
            inline=False,
        )

    embed.set_footer(text="Ticket scoreboard")

    # Reuse the stored scoreboard message if possible.
    scoreboard_id = data.get("scoreboard_message_id")
    if scoreboard_id:
        try:
            message = await channel.fetch_message(int(scoreboard_id))
            await message.edit(embed=embed)
            return
        except (discord.NotFound, discord.HTTPException, ValueError):
            pass

    try:
        message = await channel.send(embed=embed)
        await update_ticket_data(
            channel,
            scoreboard_message_id=message.id,
        )
    except discord.HTTPException:
        pass


def get_ign(member):
    return igns.get(str(member.id))


# ============================================================
# CREATE SPAWNER TICKET
# ============================================================

async def create_spawner_ticket(
    interaction,
    spawner,
    amount,
    action,
):
    guild = interaction.guild
    user = interaction.user

    if not guild:
        await interaction.response.send_message(
            "❌ This can only be used inside a server.",
            ephemeral=True,
        )
        return

    # One active ticket
    existing = active_ticket_for_user(
        guild,
        user.id,
    )

    if existing:
        await interaction.response.send_message(
            f"❌ You already have an open ticket: "
            f"{existing.mention}",
            ephemeral=True,
        )
        return

    # Cooldown
    cooldown = cooldowns.get(
        str(user.id),
        0,
    )

    if time.time() < cooldown:

        remaining = max(
            1,
            int(cooldown - time.time()),
        )

        await interaction.response.send_message(
            f"⏳ Please wait **{remaining} seconds** "
            f"before opening another ticket.",
            ephemeral=True,
        )

        return

    # Validate amount
    if amount <= 0:
        await interaction.response.send_message(
            "❌ Amount must be greater than 0.",
            ephemeral=True,
        )
        return

    if action == "BUY":

        if amount < MINIMUM_BUY:
            await interaction.response.send_message(
                f"❌ Minimum BUY amount is "
                f"**{MINIMUM_BUY} spawners**.",
                ephemeral=True,
            )
            return

        available = stock.get(
            spawner,
            0,
        )

        if available < amount:

            await interaction.response.send_message(
                f"❌ Not enough **{spawner}** stock.\n"
                f"Available: **{available}**",
                ephemeral=True,
            )

            return

    category = await get_or_create_category(
        guild,
        TICKET_CATEGORY_NAME,
    )

    order_id = next_order_id()

    channel_name = clean_channel_name(
        f"{action.lower()}-{spawner}-"
        f"{user.name}-{order_id}"
    )

    overwrites = build_ticket_overwrites(
        guild,
        user,
    )

    try:

        channel = await guild.create_text_channel(
            channel_name,
            category=category,
            overwrites=overwrites,
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ I don't have permission to create ticket channels.",
            ephemeral=True,
        )

        return

    except discord.HTTPException:

        await interaction.response.send_message(
            "❌ Discord failed to create the ticket channel.",
            ephemeral=True,
        )

        return

    # Price
    if action == "BUY":

        discounted = get_deal(spawner)

        if discounted:
            price_per = discounted
        else:
            price_per = buy_prices[spawner]

    else:
        price_per = sell_prices[spawner]

    total = price_per * amount

    # Topic
    topic = (
        f"type=spawner|"
        f"user_id={user.id}|"
        f"action={action}|"
        f"spawner={spawner}|"
        f"amount={amount}|"
        f"order_id={order_id}|"
        f"price_per={price_per}|"
        f"total={total}|"
        f"claimed_by=|"
        f"reservation=0|"
        f"completed=0|"
        f"priority=0"
    )

    try:
        await channel.edit(
            topic=topic
        )
    except discord.HTTPException:
        pass

    # Save order
    orders[order_id] = {
        "id": order_id,
        "user_id": user.id,
        "user": str(user),
        "type": action,
        "ticket_type": "SPAWNER",
        "spawner": spawner,
        "amount": amount,
        "price_per": price_per,
        "total": total,
        "admin": None,
        "admin_id": None,
        "status": "OPEN",
        "created": int(time.time()),
    }

    save_json(
        ORDERS_FILE,
        orders,
    )

    # Embed
    embed = discord.Embed(
        title=f"🎫 {action} TICKET",
        description=(
            f"Welcome {user.mention}!\n\n"
            f"**An Admin will assist you soon.**"
        ),
        color=discord.Color.blue(),
    )

    embed.add_field(
        name="🧾 Order ID",
        value=f"#{order_id}",
        inline=True,
    )

    embed.add_field(
        name="📦 Spawner",
        value=spawner,
        inline=True,
    )

    embed.add_field(
        name="🔢 Amount",
        value=str(amount),
        inline=True,
    )

    embed.add_field(
        name="💰 Total",
        value=format_amount(total),
        inline=True,
    )

    if action == "BUY":

        embed.add_field(
            name="💳 Payment",
            value=(
                "Wait for an Admin to claim the ticket.\n"
                "The Admin will provide the Minecraft "
                "username to pay."
            ),
            inline=False,
        )

    else:

        embed.add_field(
            name="📦 Selling Process",
            value=(
                "Wait for an Admin to claim the ticket.\n"
                "You will TP to the Admin and drop "
                "the spawners."
            ),
            inline=False,
        )

    try:

        await channel.send(
            content=(
                f"🚨 **NEW TICKET — STAFF ATTENTION:**\n"
                f"{ticket_staff_mentions(guild, 'spawner')} "
                f"{user.mention} "
                f"{bot.user.mention}"
            ),
            embed=embed,
            view=TicketControlView(),
        )

        await refresh_ticket_scoreboard(channel)

    except discord.HTTPException:

        await channel.delete(
            reason="Failed to send ticket message"
        )

        await interaction.response.send_message(
            "❌ I couldn't send the ticket message.",
            ephemeral=True,
        )

        return

    await interaction.response.send_message(
        f"✅ Ticket created: {channel.mention}",
        ephemeral=True,
    )


# ============================================================
# CREATE SERVICE TICKET
# ============================================================

async def create_service_ticket(
    interaction,
    service_name,
    minecraft_name,
    description,
):
    guild = interaction.guild
    user = interaction.user

    existing = active_ticket_for_user(
        guild,
        user.id,
    )

    if existing:
        await interaction.response.send_message(
            f"❌ You already have an open ticket: "
            f"{existing.mention}",
            ephemeral=True,
        )
        return

    cooldown = cooldowns.get(
        str(user.id),
        0,
    )

    if time.time() < cooldown:

        remaining = max(
            1,
            int(cooldown - time.time()),
        )

        await interaction.response.send_message(
            f"⏳ Please wait **{remaining} seconds** "
            f"before opening another ticket.",
            ephemeral=True,
        )

        return

    category = await get_or_create_category(
        guild,
        SERVICE_CATEGORY_NAME,
    )

    order_id = next_order_id()

    channel_name = clean_channel_name(
        f"service-{service_name}-"
        f"{user.name}-{order_id}"
    )

    overwrites = build_ticket_overwrites(
        guild,
        user,
    )

    try:

        channel = await guild.create_text_channel(
            channel_name,
            category=category,
            overwrites=overwrites,
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ I don't have permission to create ticket channels.",
            ephemeral=True,
        )

        return

    topic = (
        f"type=service|"
        f"user_id={user.id}|"
        f"service={service_name}|"
        f"minecraft_name={minecraft_name}|"
        f"order_id={order_id}|"
        f"claimed_by=|"
        f"completed=0|"
        f"priority=0"
    )

    try:
        await channel.edit(
            topic=topic
        )
    except discord.HTTPException:
        pass

    orders[order_id] = {
        "id": order_id,
        "user_id": user.id,
        "user": str(user),
        "type": "SERVICE",
        "service": service_name,
        "minecraft_name": minecraft_name,
        "description": description,
        "admin": None,
        "admin_id": None,
        "status": "OPEN",
        "created": int(time.time()),
    }

    save_json(
        ORDERS_FILE,
        orders,
    )

    if service_name in ("Base Building", "Digging"):

        title = "BASE BUILDING" if service_name == "Base Building" else "DIGGING"
        instructions = (
            f"🛠️ **{title}**\n\n"
            "• Explain/upload the work details in this ticket.\n"
            "• Discuss the job with the assigned staff.\n"
            "• Price is negotiated before work begins.\n"
            "• Agree on the final price before work starts."
        )

    else:

        instructions = (
            "📍 **COORDINATES SERVICE**\n\n"
            "• An Admin will claim the ticket.\n"
            "• You may TP to the Admin if instructed.\n"
            "• Follow the Admin's service/payment instructions.\n"
            "• The listed price applies to this service."
        )

    embed = discord.Embed(
        title=f"🛠️ {service_name}",
        description=(
            f"Welcome {user.mention}!\n\n"
            f"**An Admin will assist you soon.**\n\n"
            f"🎮 **Minecraft Username:**\n"
            f"`{minecraft_name}`\n\n"
            f"📝 **Description / Location:**\n"
            f"{description}"
        ),
        color=discord.Color.purple(),
    )

    embed.add_field(
        name="🧾 Order ID",
        value=f"#{order_id}",
        inline=True,
    )

    embed.add_field(
        name="💰 Price",
        value=SERVICES.get(
            service_name,
            "Negotiable",
        ),
        inline=True,
    )

    embed.add_field(
        name="📋 Instructions",
        value=instructions,
        inline=False,
    )

    await channel.send(
        content=(
            f"🚨 **NEW SERVICE TICKET — STAFF ATTENTION:**\n"
            f"{ticket_staff_mentions(guild, 'service', service_name)} "
            f"{user.mention} "
            f"{bot.user.mention}"
        ),
        embed=embed,
        view=ServiceTicketControlView(),
    )

    await refresh_ticket_scoreboard(channel)

    await interaction.response.send_message(
        f"✅ Service ticket created: {channel.mention}",
        ephemeral=True,
    )


# ============================================================
# BUY MODAL
# ============================================================

class BuySpawnerModal(Modal):

    def __init__(self, spawner):
        super().__init__(
            title=f"Buy {spawner}"
        )

        self.spawner = spawner

        self.amount = TextInput(
            label="Amount",
            placeholder=f"Minimum {MINIMUM_BUY}",
            required=True,
            max_length=10,
        )

        self.add_item(
            self.amount
        )

    async def on_submit(
        self,
        interaction,
    ):
        try:
            amount = int(
                self.amount.value
            )
        except ValueError:

            await interaction.response.send_message(
                "❌ Please enter a valid number.",
                ephemeral=True,
            )

            return

        await create_spawner_ticket(
            interaction,
            self.spawner,
            amount,
            "BUY",
        )


# ============================================================
# SELL MODAL
# ============================================================

class SellSpawnerModal(Modal):

    def __init__(self, spawner):
        super().__init__(
            title=f"Sell {spawner}"
        )

        self.spawner = spawner

        self.amount = TextInput(
            label="Amount",
            placeholder="How many spawners?",
            required=True,
            max_length=10,
        )

        self.add_item(
            self.amount
        )

    async def on_submit(
        self,
        interaction,
    ):
        try:
            amount = int(
                self.amount.value
            )
        except ValueError:

            await interaction.response.send_message(
                "❌ Please enter a valid number.",
                ephemeral=True,
            )

            return

        if amount <= 0:

            await interaction.response.send_message(
                "❌ Amount must be greater than 0.",
                ephemeral=True,
            )

            return

        await create_spawner_ticket(
            interaction,
            self.spawner,
            amount,
            "SELL",
        )


# ============================================================
# COORDINATES MODAL
# ============================================================

class CoordinatesModal(Modal):

    def __init__(self, service_name):
        super().__init__(
            title=service_name
        )

        self.service_name = service_name

        self.minecraft_name = TextInput(
            label="Minecraft Username",
            placeholder="Your Minecraft username",
            required=True,
            max_length=32,
        )

        self.coordinates = TextInput(
            label="Coordinates / Location",
            placeholder="X 100, Y 70, Z -250",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1000,
        )

        self.add_item(
            self.minecraft_name
        )

        self.add_item(
            self.coordinates
        )

    async def on_submit(
        self,
        interaction,
    ):
        await create_service_ticket(
            interaction,
            self.service_name,
            self.minecraft_name.value,
            self.coordinates.value,
        )


# ============================================================
# DIGGING MODAL
# ============================================================

class DiggingModal(Modal):

    def __init__(self):
        super().__init__(title="Digging")

        self.minecraft_name = TextInput(
            label="Minecraft Username",
            placeholder="Your Minecraft username",
            required=True,
            max_length=32,
        )

        self.description = TextInput(
            label="Digging Details",
            placeholder="What needs digging and where?",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=2000,
        )

        self.add_item(self.minecraft_name)
        self.add_item(self.description)

    async def on_submit(self, interaction):
        await create_service_ticket(
            interaction,
            "Digging",
            self.minecraft_name.value,
            self.description.value,
        )


# ============================================================
# BASE BUILDING MODAL
# ============================================================

class BaseBuildingModal(Modal):

    def __init__(self):
        super().__init__(
            title="Base Building"
        )

        self.minecraft_name = TextInput(
            label="Minecraft Username",
            placeholder="Your Minecraft username",
            required=True,
            max_length=32,
        )

        self.description = TextInput(
            label="Base Description",
            placeholder="Describe what you want built",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=2000,
        )

        self.add_item(
            self.minecraft_name
        )

        self.add_item(
            self.description
        )

    async def on_submit(
        self,
        interaction,
    ):
        await create_service_ticket(
            interaction,
            "Base Building",
            self.minecraft_name.value,
            self.description.value,
        )


# ============================================================
# SPAWNER SHOP BUTTONS
# ============================================================

class SpawnerPanelView(View):

    def __init__(self):
        super().__init__(
            timeout=None
        )

    @discord.ui.button(
        label="Buy Skeleton",
        style=discord.ButtonStyle.green,
        custom_id="shop_buy_skeleton",
    )
    async def buy_skeleton(
        self,
        interaction,
        button,
    ):
        await interaction.response.send_modal(
            BuySpawnerModal("Skeleton")
        )

    @discord.ui.button(
        label="Buy Iron Golem",
        style=discord.ButtonStyle.green,
        custom_id="shop_buy_iron",
    )
    async def buy_iron(
        self,
        interaction,
        button,
    ):
        await interaction.response.send_modal(
            BuySpawnerModal("Iron Golem")
        )

    @discord.ui.button(
        label="Buy Creeper",
        style=discord.ButtonStyle.green,
        custom_id="shop_buy_creeper",
    )
    async def buy_creeper(
        self,
        interaction,
        button,
    ):
        await interaction.response.send_modal(
            BuySpawnerModal("Creeper")
        )

    @discord.ui.button(
        label="Sell Skeleton",
        style=discord.ButtonStyle.red,
        custom_id="shop_sell_skeleton",
    )
    async def sell_skeleton(
        self,
        interaction,
        button,
    ):
        await interaction.response.send_modal(
            SellSpawnerModal("Skeleton")
        )

    @discord.ui.button(
        label="Sell Iron Golem",
        style=discord.ButtonStyle.red,
        custom_id="shop_sell_iron",
    )
    async def sell_iron(
        self,
        interaction,
        button,
    ):
        await interaction.response.send_modal(
            SellSpawnerModal("Iron Golem")
        )

    @discord.ui.button(
        label="Sell Creeper",
        style=discord.ButtonStyle.red,
        custom_id="shop_sell_creeper",
    )
    async def sell_creeper(
        self,
        interaction,
        button,
    ):
        await interaction.response.send_modal(
            SellSpawnerModal("Creeper")
        )


# ============================================================
# SERVICE BUTTONS
# ============================================================

class ServicePanelView(View):

    def __init__(self):
        super().__init__(
            timeout=None
        )

    @discord.ui.button(
        label="Low Cords",
        style=discord.ButtonStyle.primary,
        custom_id="service_low_cords",
    )
    async def low_cords(
        self,
        interaction,
        button,
    ):
        await interaction.response.send_modal(
            CoordinatesModal("Low Cords")
        )

    @discord.ui.button(
        label="Mid Cords",
        style=discord.ButtonStyle.primary,
        custom_id="service_mid_cords",
    )
    async def mid_cords(
        self,
        interaction,
        button,
    ):
        await interaction.response.send_modal(
            CoordinatesModal("Mid Cords")
        )

    @discord.ui.button(
        label="Good Cords",
        style=discord.ButtonStyle.primary,
        custom_id="service_good_cords",
    )
    async def good_cords(
        self,
        interaction,
        button,
    ):
        await interaction.response.send_modal(
            CoordinatesModal("Good Cords")
        )

    @discord.ui.button(
        label="God Cords",
        style=discord.ButtonStyle.primary,
        custom_id="service_god_cords",
    )
    async def god_cords(
        self,
        interaction,
        button,
    ):
        await interaction.response.send_modal(
            CoordinatesModal("God Cords")
        )

    @discord.ui.button(
        label="Digging",
        style=discord.ButtonStyle.secondary,
        custom_id="service_digging",
    )
    async def digging(
        self,
        interaction,
        button,
    ):
        await interaction.response.send_modal(
            DiggingModal()
        )

    @discord.ui.button(
        label="Base Building",
        style=discord.ButtonStyle.secondary,
        custom_id="service_base_building",
    )
    async def base_building(
        self,
        interaction,
        button,
    ):
        await interaction.response.send_modal(
            BaseBuildingModal()
        )


# ============================================================
# CLAIM TICKET
# ============================================================

async def claim_ticket(interaction):

    if not await require_ticket_manager(interaction):
        return

    channel = interaction.channel

    if not is_ticket_channel(channel):

        await interaction.response.send_message(
            "❌ This is not a ticket channel.",
            ephemeral=True,
        )

        return

    data = get_ticket_data(channel)

    if data.get("claimed_by"):

        await interaction.response.send_message(
            "❌ This ticket has already been claimed.",
            ephemeral=True,
        )

        return

    ticket_type = data.get("type")
    action = data.get("action")

    # --------------------------------------------------------
    # BUY STOCK RESERVATION
    # --------------------------------------------------------

    if ticket_type == "spawner" and action == "BUY":

        spawner = data.get("spawner")

        try:
            amount = int(
                data.get("amount", 0)
            )
        except ValueError:
            amount = 0

        available = stock.get(
            spawner,
            0,
        )

        if available < amount:

            await interaction.response.send_message(
                f"❌ There is no longer enough "
                f"**{spawner}** stock.\n"
                f"Available: **{available}**",
                ephemeral=True,
            )

            return

        # Reserve BEFORE marking claimed
        stock[spawner] = (
            available - amount
        )

        save_json(
            STOCK_FILE,
            stock,
        )

        await update_ticket_data(
            channel,
            reservation=amount,
        )

        await check_low_stock(
            interaction.guild,
            spawner,
        )

        await update_shop_panel(
            interaction.guild
        )

    # --------------------------------------------------------
    # CLAIM
    # --------------------------------------------------------

    await update_ticket_data(
        channel,
        claimed_by=interaction.user.id,
    )

    order_id = data.get(
        "order_id"
    )

    if order_id in orders:

        orders[order_id]["admin"] = str(
            interaction.user
        )

        orders[order_id]["admin_id"] = (
            interaction.user.id
        )

        orders[order_id]["status"] = "CLAIMED"
        orders[order_id]["claimed_by_name"] = str(interaction.user)
        orders[order_id]["claimed_by_ign"] = get_ign(interaction.user) or ""

        save_json(
            ORDERS_FILE,
            orders,
        )

    customer = interaction.guild.get_member(
        int(data.get("user_id", 0))
    )

    await interaction.response.send_message(
        f"✅ You claimed **Order #{order_id}**.",
        ephemeral=True,
    )

    if customer:

        staff_ign = get_ign(interaction.user)
        ign_line = (
            f"\n🎮 In-game name: `{staff_ign}`"
            if staff_ign else ""
        )
        await channel.send(
            f"👑 **{interaction.user.display_name}** "
            f"has claimed this ticket.{ign_line}\n\n"
            f"{customer.mention} — "
            f"you can now TP to the claiming staff member "
            f"if instructed."
        )

    await refresh_ticket_scoreboard(channel)


# ============================================================
# PRIORITY
# ============================================================

async def priority_ticket(interaction):

    if not await require_ticket_manager(interaction):
        return

    channel = interaction.channel

    data = get_ticket_data(
        channel
    )

    current = data.get(
        "priority",
        "0",
    )

    if current == "1":

        await update_ticket_data(
            channel,
            priority=0,
        )

        new_name = channel.name.replace(
            "priority-",
            "",
            1,
        )

        try:
            await channel.edit(
                name=new_name
            )
        except discord.HTTPException:
            pass

        await interaction.response.send_message(
            "⬇️ Ticket priority removed."
        )

        await refresh_ticket_scoreboard(channel)

    else:

        await update_ticket_data(
            channel,
            priority=1,
        )

        if not channel.name.startswith(
            "priority-"
        ):

            new_name = (
                f"priority-{channel.name}"
            )[:100]

            try:
                await channel.edit(
                    name=new_name
                )
            except discord.HTTPException:
                pass

        await interaction.response.send_message(
            "🚨 **Ticket marked as PRIORITY.**"
        )

        await refresh_ticket_scoreboard(channel)


# ============================================================
# ============================================================
# REVIEW SYSTEM
# ============================================================

LOW_RATING_FEEDBACK_USER_ID = 1492159355620167720


def get_review_order_id(message):
    if not message or not message.embeds:
        return None

    footer = message.embeds[0].footer.text or ""
    match = re.search(r"Order #([0-9]+)", footer)
    return match.group(1) if match else None


def review_already_submitted(order_id, customer_id):
    return any(
        str(review.get("order_id")) == str(order_id)
        and int(review.get("user_id", 0)) == int(customer_id)
        for review in reviews
    )


async def save_review_record(order_id, customer, rating, feedback=None):
    if review_already_submitted(order_id, customer.id):
        return False

    data = orders.get(str(order_id), {})

    review = {
        "order_id": str(order_id),
        "user_id": customer.id,
        "user": str(customer),
        "rating": int(rating),
        "admin": data.get("admin", "Unknown"),
        "feedback": feedback or "",
        "timestamp": int(time.time()),
    }

    reviews.append(review)
    save_json(REVIEWS_FILE, reviews)

    admin_id = data.get("admin_id")
    if admin_id:
        key = str(admin_id)

        if key not in admin_stats:
            admin_stats[key] = {
                "name": data.get("admin", "Unknown"),
                "tickets_completed": 0,
                "payments_handled": 0,
                "revenue_handled": 0,
                "reviews": [],
            }

        admin_stats[key].setdefault("reviews", []).append(int(rating))
        save_json(ADMIN_STATS_FILE, admin_stats)

    return True


class LowRatingFeedbackModal(Modal, title="Low Rating Feedback"):

    feedback = TextInput(
        label="What went wrong?",
        placeholder="Tell us what we can improve...",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1000,
    )

    def __init__(self, order_id, rating):
        super().__init__()
        self.order_id = str(order_id)
        self.rating = int(rating)

    async def on_submit(self, interaction):
        if review_already_submitted(self.order_id, interaction.user.id):
            await interaction.response.send_message(
                "❌ A review has already been submitted for this order.",
                ephemeral=True,
            )
            return

        feedback = self.feedback.value.strip()
        if not feedback:
            await interaction.response.send_message(
                "❌ Please enter feedback.",
                ephemeral=True,
            )
            return

        saved = await save_review_record(
            self.order_id,
            interaction.user,
            self.rating,
            feedback,
        )

        if not saved:
            await interaction.response.send_message(
                "❌ A review has already been submitted for this order.",
                ephemeral=True,
            )
            return

        target = interaction.client.get_user(LOW_RATING_FEEDBACK_USER_ID)
        if target is None:
            try:
                target = await interaction.client.fetch_user(
                    LOW_RATING_FEEDBACK_USER_ID
                )
            except discord.HTTPException:
                target = None

        if target:
            try:
                await target.send(
                    f"⚠️ **Low Customer Rating**\n"
                    f"Customer: {interaction.user} ({interaction.user.id})\n"
                    f"Order: **#{self.order_id}**\n"
                    f"Rating: **{self.rating}/5**\n"
                    f"Feedback: {feedback}"
                )
            except discord.HTTPException:
                pass

        await interaction.response.send_message(
            f"⭐ Thank you for your feedback on Order **#{self.order_id}**.",
            ephemeral=True,
        )


class ReviewView(View):

    def __init__(self):
        super().__init__(timeout=None)

    async def handle_rating(self, interaction, rating):
        order_id = get_review_order_id(interaction.message)

        if not order_id:
            await interaction.response.send_message(
                "❌ I could not identify this order.",
                ephemeral=True,
            )
            return

        if review_already_submitted(order_id, interaction.user.id):
            await interaction.response.send_message(
                "❌ A review has already been submitted for this order.",
                ephemeral=True,
            )
            return

        if rating <= 2:
            await interaction.response.send_modal(
                LowRatingFeedbackModal(order_id, rating)
            )
            return

        saved = await save_review_record(
            order_id,
            interaction.user,
            rating,
        )

        if not saved:
            await interaction.response.send_message(
                "❌ A review has already been submitted for this order.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"⭐ Thank you! You gave Order **#{order_id}** **{rating}/5 stars**.",
            ephemeral=True,
        )

    @discord.ui.button(label="1 ⭐", style=discord.ButtonStyle.secondary, custom_id="customer_review_1")
    async def one(self, interaction, button):
        await self.handle_rating(interaction, 1)

    @discord.ui.button(label="2 ⭐", style=discord.ButtonStyle.secondary, custom_id="customer_review_2")
    async def two(self, interaction, button):
        await self.handle_rating(interaction, 2)

    @discord.ui.button(label="3 ⭐", style=discord.ButtonStyle.secondary, custom_id="customer_review_3")
    async def three(self, interaction, button):
        await self.handle_rating(interaction, 3)

    @discord.ui.button(label="4 ⭐", style=discord.ButtonStyle.secondary, custom_id="customer_review_4")
    async def four(self, interaction, button):
        await self.handle_rating(interaction, 4)

    @discord.ui.button(label="5 ⭐", style=discord.ButtonStyle.success, custom_id="customer_review_5")
    async def five(self, interaction, button):
        await self.handle_rating(interaction, 5)


# ============================================================
# REVIEW REQUEST
# ============================================================

async def send_review_request(channel, order_id, customer_id):
    try:
        customer = channel.guild.get_member(int(customer_id))

        if customer is None:
            customer = await bot.fetch_user(int(customer_id))

        review_embed = discord.Embed(
            title="⭐ CUSTOMER REVIEW",
            description=(
                "Your ticket has been closed.\n\n"
                "Please rate your experience from **1–5 stars**."
            ),
            color=discord.Color.gold(),
        )
        review_embed.set_footer(text=f"Order #{order_id}")

        await customer.send(
            embed=review_embed,
            view=ReviewView(),
        )
        return True

    except (discord.Forbidden, discord.HTTPException, ValueError):
        return False


# COMPLETE TICKET
# ============================================================

async def complete_ticket(interaction):

    if not await require_ticket_manager(interaction):
        return

    channel = interaction.channel

    if not is_ticket_channel(channel):

        await interaction.response.send_message(
            "❌ This is not a ticket channel.",
            ephemeral=True,
        )

        return

    data = get_ticket_data(
        channel
    )

    if data.get("completed") == "1":

        await interaction.response.send_message(
            "⚠️ This ticket is already completed.",
            ephemeral=True,
        )

        return

    ticket_type = data.get(
        "type"
    )

    action = data.get(
        "action"
    )

    order_id = data.get(
        "order_id",
        "Unknown",
    )

    # --------------------------------------------------------
    # BUY
    # --------------------------------------------------------

    if (
        ticket_type == "spawner"
        and action == "BUY"
    ):

        reservation = int(
            data.get(
                "reservation",
                0,
            )
        )

        if reservation <= 0:

            await interaction.response.send_message(
                "❌ This BUY ticket has no stock reservation. "
                "The Admin must claim it first.",
                ephemeral=True,
            )

            return

    # --------------------------------------------------------
    # SELL
    # --------------------------------------------------------

    elif (
        ticket_type == "spawner"
        and action == "SELL"
    ):

        spawner = data.get(
            "spawner"
        )

        amount = int(
            data.get(
                "amount",
                0,
            )
        )

        stock[spawner] = (
            stock.get(
                spawner,
                0,
            )
            + amount
        )

        save_json(
            STOCK_FILE,
            stock,
        )

        await check_low_stock(
            interaction.guild,
            spawner,
        )

        await update_shop_panel(
            interaction.guild
        )

    # --------------------------------------------------------
    # MARK COMPLETE
    # --------------------------------------------------------

    await update_ticket_data(
        channel,
        completed=1,
    )

    if order_id in orders:

        orders[order_id]["status"] = "COMPLETED"

        orders[order_id]["completed_by"] = str(
            interaction.user
        )

        orders[order_id]["completed_at"] = int(
            time.time()
        )

        save_json(
            ORDERS_FILE,
            orders,
        )

    add_admin_stat(
        interaction.user,
        "tickets_completed",
    )

    await interaction.response.send_message(
        f"✅ **Order #{order_id} completed.**\n"
        f"Completed by {interaction.user.mention}."
    )

    await refresh_ticket_scoreboard(channel, "COMPLETED")

    # --------------------------------------------------------
    # TRANSCRIPT
# ============================================================

async def create_transcript(channel):

    guild = channel.guild

    transcript_channel = discord.utils.get(
        guild.text_channels,
        name=TRANSCRIPT_CHANNEL_NAME,
    )

    if not transcript_channel:

        try:

            transcript_channel = (
                await guild.create_text_channel(
                    TRANSCRIPT_CHANNEL_NAME
                )
            )

        except discord.HTTPException:

            return False

    data = get_ticket_data(
        channel
    )

    lines = [
        "===== TICKET TRANSCRIPT =====",
        f"Channel: {channel.name}",
        f"Order ID: #{data.get('order_id', 'Unknown')}",
        f"Owner ID: {data.get('user_id', 'Unknown')}",
        f"Type: {data.get('type', 'Unknown')}",
        "==============================",
    ]

    try:

        async for message in channel.history(
            limit=None,
            oldest_first=True,
        ):

            timestamp = (
                message.created_at
                .strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            )

            content = (
                message.content
                or "[No text]"
            )

            if message.attachments:

                attachments = ", ".join(
                    attachment.url
                    for attachment in message.attachments
                )

                content += (
                    f" | Attachments: {attachments}"
                )

            lines.append(
                f"[{timestamp}] "
                f"{message.author}: "
                f"{content}"
            )

    except Exception as error:

        lines.append(
            f"Transcript error: {error}"
        )

    text = "\n".join(
        lines
    )

    # Discord message limit
    for index in range(
        0,
        len(text),
        1900,
    ):

        chunk = text[
            index:index + 1900
        ]

        try:

            await transcript_channel.send(
                f"```text\n{chunk}\n```"
            )

        except discord.HTTPException:
            pass

    return True


# ============================================================
# CLOSE TICKET
# ============================================================

async def close_ticket(interaction):

    if not is_admin(interaction.user):

        await interaction.response.send_message(
            "❌ Only Admins can close tickets.",
            ephemeral=True,
        )

        return

    channel = interaction.channel

    if not is_ticket_channel(channel):

        await interaction.response.send_message(
            "❌ This is not a ticket channel.",
            ephemeral=True,
        )

        return

    data = get_ticket_data(
        channel
    )

    user_id = data.get(
        "user_id"
    )

    ticket_type = data.get(
        "type"
    )

    action = data.get(
        "action"
    )

    spawner = data.get(
        "spawner"
    )

    completed = data.get(
        "completed",
        "0",
    )

    # --------------------------------------------------------
    # RETURN BUY RESERVATION
    # --------------------------------------------------------

    if (
        ticket_type == "spawner"
        and action == "BUY"
        and completed != "1"
    ):

        reservation = int(
            data.get(
                "reservation",
                0,
            )
        )

        if (
            reservation > 0
            and spawner
        ):

            stock[spawner] = (
                stock.get(
                    spawner,
                    0,
                )
                + reservation
            )

            save_json(
                STOCK_FILE,
                stock,
            )

            await check_low_stock(
                interaction.guild,
                spawner,
            )

            await update_shop_panel(
                interaction.guild
            )

            await update_ticket_data(
                channel,
                reservation=0,
            )

    # --------------------------------------------------------
    # COOLDOWN
    # --------------------------------------------------------

    if user_id:

        cooldowns[str(user_id)] = (
            time.time()
            + TICKET_COOLDOWN
        )

        save_json(
            COOLDOWNS_FILE,
            cooldowns,
        )

    # --------------------------------------------------------
    # ORDER STATUS
    # --------------------------------------------------------

    order_id = data.get(
        "order_id"
    )

    if order_id in orders:

        orders[order_id]["status"] = "CLOSED"

        orders[order_id]["closed_by"] = str(
            interaction.user
        )

        orders[order_id]["closed_at"] = int(
            time.time()
        )

        save_json(
            ORDERS_FILE,
            orders,
        )

    await interaction.response.send_message(
        "🔒 Ticket closing and saving transcript..."
    )

    await create_transcript(
        channel
    )

    # Send the review request before deleting the ticket.
    if user_id and order_id:
        await send_review_request(
            channel,
            order_id,
            user_id,
        )


    await asyncio.sleep(
        3
    )

    try:

        await channel.delete(
            reason=(
                f"Ticket closed by "
                f"{interaction.user}"
            )
        )

    except discord.HTTPException:
        pass


# ============================================================
# TICKET CONTROL BUTTONS
# ============================================================

class TicketControlView(View):

    def __init__(self):
        super().__init__(
            timeout=None
        )

    @discord.ui.button(
        label="Claim",
        emoji="👑",
        style=discord.ButtonStyle.success,
        custom_id="ticket_claim",
    )
    async def claim(
        self,
        interaction,
        button,
    ):
        await claim_ticket(
            interaction
        )

    @discord.ui.button(
        label="Priority",
        emoji="🚨",
        style=discord.ButtonStyle.primary,
        custom_id="ticket_priority",
    )
    async def priority(
        self,
        interaction,
        button,
    ):
        await priority_ticket(
            interaction
        )

    @discord.ui.button(
        label="Complete",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="ticket_complete",
    )
    async def complete(
        self,
        interaction,
        button,
    ):
        await complete_ticket(
            interaction
        )

    @discord.ui.button(
        label="Close",
        emoji="🔒",
        style=discord.ButtonStyle.danger,
        custom_id="ticket_close",
    )
    async def close(
        self,
        interaction,
        button,
    ):
        await close_ticket(
            interaction
        )


class ServiceTicketControlView(View):

    def __init__(self):
        super().__init__(
            timeout=None
        )

    @discord.ui.button(
        label="Claim",
        emoji="👑",
        style=discord.ButtonStyle.success,
        custom_id="service_ticket_claim",
    )
    async def claim(
        self,
        interaction,
        button,
    ):
        await claim_ticket(
            interaction
        )

    @discord.ui.button(
        label="Priority",
        emoji="🚨",
        style=discord.ButtonStyle.primary,
        custom_id="service_ticket_priority",
    )
    async def priority(
        self,
        interaction,
        button,
    ):
        await priority_ticket(
            interaction
        )

    @discord.ui.button(
        label="Complete",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="service_ticket_complete",
    )
    async def complete(
        self,
        interaction,
        button,
    ):
        await complete_ticket(
            interaction
        )

    @discord.ui.button(
        label="Close",
        emoji="🔒",
        style=discord.ButtonStyle.danger,
        custom_id="service_ticket_close",
    )
    async def close(
        self,
        interaction,
        button,
    ):
        await close_ticket(
            interaction
        )


# ============================================================
# SETUP SHOP
# ============================================================

@bot.command(
    name="SetupShop"
)
async def setup_shop(ctx):

    if not await require_admin(ctx):
        return

    embed = build_shop_embed()

    await ctx.send(
        embed=embed,
        view=SpawnerPanelView(),
    )


# ============================================================
# SETUP TICKETS
# ============================================================

@bot.command(
    name="SetupTickets"
)
async def setup_tickets(ctx):

    if not await require_admin(ctx):
        return

    embed = build_shop_embed()

    await ctx.send(
        embed=embed,
        view=SpawnerPanelView(),
    )


# ============================================================
# SETUP SERVICES
# ============================================================

@bot.command(
    name="SetupServices"
)
async def setup_services(ctx):

    if not await require_admin(ctx):
        return

    embed = discord.Embed(
        title="🛠️ SERVICES",
        description=(
            "Choose a service below.\n\n"
            "A private ticket will be created "
            "for you and an Admin will assist you."
        ),
        color=discord.Color.purple(),
    )

    for name, price in SERVICES.items():

        if name in ("Base Building", "Digging"):


            description = (
                "🏗️ Negotiable price"
            )

        else:

            description = (
                f"💰 {price}"
            )

        embed.add_field(
            name=name,
            value=description,
            inline=False,
        )

    embed.set_footer(
        text="Services • Private tickets"
    )

    await ctx.send(
        embed=embed,
        view=ServicePanelView(),
    )


# ============================================================
# STOCK
# ============================================================

@bot.command(
    name="Stock"
)
async def stock_command(ctx):

    embed = discord.Embed(
        title="📦 SPAWNER STOCK",
        color=discord.Color.blue(),
    )

    for spawner, amount in stock.items():

        if amount <= 0:

            status = (
                "🔴 OUT OF STOCK"
            )

        elif amount <= LOW_STOCK_LIMIT:

            status = (
                f"⚠️ LOW STOCK — {amount}"
            )

        else:

            status = (
                f"🟢 {amount}"
            )

        embed.add_field(
            name=spawner,
            value=status,
            inline=False,
        )

    await ctx.send(
        embed=embed
    )


# ============================================================
# SET STOCK
# ============================================================

@bot.command(
    name="SetStock"
)
async def set_stock(
    ctx,
    spawner=None,
    amount=None,
):

    if not await require_admin(ctx):
        return

    if spawner is None or amount is None:

        await ctx.send(
            "Usage: `!SetStock <Spawner> <Amount>`"
        )

        return

    # Allows multi-word Iron Golem
    if (
        spawner.lower() == "iron"
        and amount is not None
    ):
        # Normal syntax is !SetStock iron 100
        pass

    spawner_name = normalize_spawner(
        spawner
    )

    if not spawner_name:

        await ctx.send(
            "❌ Unknown spawner.\n"
            "Available: Skeleton, Iron Golem, Creeper"
        )

        return

    try:

        amount = int(
            amount
        )

    except ValueError:

        await ctx.send(
            "❌ Amount must be a number."
        )

        return

    if amount < 0:

        await ctx.send(
            "❌ Amount cannot be negative."
        )

        return

    stock[spawner_name] = amount

    save_json(
        STOCK_FILE,
        stock,
    )

    await update_shop_panel(
        ctx.guild
    )

    await ctx.send(
        f"✅ **{spawner_name}** stock "
        f"set to **{amount}**."
    )

    await check_low_stock(
        ctx.guild,
        spawner_name,
    )


# ============================================================
# PRICES
# ============================================================

@bot.command(
    name="Prices"
)
async def prices(ctx):

    await ctx.send(
        embed=build_shop_embed()
    )


# ============================================================
# CHANGE BUY PRICE
# ============================================================

@bot.command(
    name="ChangeBuyPrice"
)
async def change_buy_price(
    ctx,
    spawner=None,
    price=None,
):

    if not await require_admin(ctx):
        return

    if spawner is None or price is None:

        await ctx.send(
            "Usage: "
            "`!ChangeBuyPrice <Spawner> <Price>`"
        )

        return

    spawner_name = normalize_spawner(
        spawner
    )

    if not spawner_name:

        await ctx.send(
            "❌ Unknown spawner."
        )

        return

    parsed = parse_amount(
        price
    )

    if parsed is None or parsed <= 0:

        await ctx.send(
            "❌ Invalid price."
        )

        return

    buy_prices[spawner_name] = parsed

    save_prices()

    await update_shop_panel(
        ctx.guild
    )

    await ctx.send(
        f"✅ **{spawner_name}** BUY price "
        f"changed to **{format_amount(parsed)}**."
    )


# ============================================================
# CHANGE SELL PRICE
# ============================================================

@bot.command(
    name="ChangeSellPrice"
)
async def change_sell_price(
    ctx,
    spawner=None,
    price=None,
):

    if not await require_admin(ctx):
        return

    if spawner is None or price is None:

        await ctx.send(
            "Usage: "
            "`!ChangeSellPrice <Spawner> <Price>`"
        )

        return

    spawner_name = normalize_spawner(
        spawner
    )

    if not spawner_name:

        await ctx.send(
            "❌ Unknown spawner."
        )

        return

    parsed = parse_amount(
        price
    )

    if parsed is None or parsed <= 0:

        await ctx.send(
            "❌ Invalid price."
        )

        return

    sell_prices[spawner_name] = parsed

    save_prices()

    await update_shop_panel(
        ctx.guild
    )

    await ctx.send(
        f"✅ **{spawner_name}** SELL price "
        f"changed to **{format_amount(parsed)}**."
    )


# ============================================================
# RANDOM DEAL
# ============================================================

@bot.command(
    name="RandomDeal"
)
async def random_deal(ctx):

    if not await require_admin(ctx):
        return

    spawner = random.choice(
        list(buy_prices.keys())
    )

    discount = random.choice(
        [5, 10, 15, 20, 25]
    )

    deals.clear()

    deals[spawner] = {
        "discount": discount,
        "created": int(
            time.time()
        ),
    }

    save_json(
        DEALS_FILE,
        deals,
    )

    await update_shop_panel(
        ctx.guild
    )

    discounted = int(
        buy_prices[spawner]
        * (100 - discount)
        / 100
    )

    await ctx.send(
        f"🔥 **RANDOM DEAL!**\n\n"
        f"📦 Spawner: **{spawner}**\n"
        f"🏷️ Discount: **{discount}% OFF**\n"
        f"💰 New price: **{format_amount(discounted)}**"
    )


# ============================================================
# CLEAR DEAL
# ============================================================

@bot.command(
    name="ClearDeal"
)
async def clear_deal(ctx):

    if not await require_admin(ctx):
        return

    deals.clear()

    save_json(
        DEALS_FILE,
        deals,
    )

    await update_shop_panel(
        ctx.guild
    )

    await ctx.send(
        "✅ All active deals have been cleared."
    )


# ============================================================
# IN-GAME NAME ASSIGNMENT
# ============================================================

@bot.command(name="Ign")
async def ign_command(ctx, member: discord.Member = None, *, minecraft_name=None):
    if not await require_admin(ctx):
        return

    if member is None or not minecraft_name:
        await ctx.send("Usage: `!Ign @User MinecraftName`")
        return

    minecraft_name = minecraft_name.strip()
    if not minecraft_name:
        await ctx.send("❌ Minecraft username cannot be empty.")
        return

    igns[str(member.id)] = minecraft_name
    save_json(IGN_FILE, igns)

    updated = 0
    for channel in ctx.guild.text_channels:
        if not is_ticket_channel(channel):
            continue
        data = get_ticket_data(channel)
        if str(data.get("user_id", "")) == str(member.id):
            await refresh_ticket_scoreboard(channel)
            updated += 1

    suffix = f" Updated {updated} ticket scoreboard(s)." if updated else ""
    await ctx.send(
        f"✅ Assigned **{minecraft_name}** as {member.mention}'s in-game name."
        f"{suffix}"
    )


# ============================================================
# DISPLAY
# ============================================================

@bot.command(
    name="Display"
)
async def display(
    ctx,
    minecraft_name=None,
):

    if not await require_admin(ctx):
        return

    if not minecraft_name:

        await ctx.send(
            "Usage: `!Display <MinecraftName>`"
        )

        return

    await ctx.send(
        f"👑 **Admin Minecraft Username:** "
        f"`{minecraft_name}`"
    )


# ============================================================
# SHOW PAYMENT / SERVICE INSTRUCTIONS
# ============================================================

@bot.command(
    name="Show"
)
async def show(
    ctx,
    minecraft_name=None,
):

    if not await require_admin(ctx):
        return

    if not minecraft_name:

        await ctx.send(
            "Usage: `!Show <MinecraftUsername>`"
        )

        return

    if not is_ticket_channel(
        ctx.channel
    ):

        await ctx.send(
            "❌ `!Show` must be used inside an active ticket."
        )

        return

    data = get_ticket_data(
        ctx.channel
    )

    ticket_type = data.get(
        "type"
    )

    # --------------------------------------------------------
    # SPAWNER
    # --------------------------------------------------------

    if ticket_type == "spawner":

        action = data.get(
            "action"
        )

        order_id = data.get(
            "order_id",
            "Unknown",
        )

        amount = int(
            data.get(
                "amount",
                0,
            )
        )

        total = int(
            data.get(
                "total",
                0,
            )
        )

        spawner = data.get(
            "spawner"
        )

        if action == "BUY":

            message = (
                f"💳 **PAYMENT INSTRUCTIONS — "
                f"ORDER #{order_id}**\n\n"
                f"👑 **Pay Admin:** "
                f"`{minecraft_name}`\n"
                f"📦 **Spawner:** {spawner}\n"
                f"🔢 **Amount:** {amount}\n"
                f"💰 **Total:** "
                f"{format_amount(total)}\n\n"
                f"**Steps:**\n"
                f"1️⃣ TP to `{minecraft_name}`.\n"
                f"2️⃣ Confirm your order.\n"
                f"3️⃣ Pay **{format_amount(total)}**.\n"
                f"4️⃣ Wait for payment confirmation.\n"
                f"5️⃣ The Admin gives you the spawners."
            )

        else:

            message = (
                f"💳 **SELL INSTRUCTIONS — "
                f"ORDER #{order_id}**\n\n"
                f"👑 **Admin:** `{minecraft_name}`\n"
                f"📦 **Spawner:** {spawner}\n"
                f"🔢 **Amount:** {amount}\n"
                f"💰 **You receive:** "
                f"{format_amount(total)}\n\n"
                f"**Steps:**\n"
                f"1️⃣ TP to `{minecraft_name}`.\n"
                f"2️⃣ Confirm the spawner amount.\n"
                f"3️⃣ Drop the spawners.\n"
                f"4️⃣ The Admin pays you "
                f"**{format_amount(total)}**.\n"
                f"5️⃣ Confirm payment received."
            )

        await ctx.send(
            message
        )

        return

    # --------------------------------------------------------
    # SERVICES
    # --------------------------------------------------------

    if ticket_type == "service":

        service = data.get(
            "service"
        )

        order_id = data.get(
            "order_id",
            "Unknown",
        )

        if service == "Base Building":

            message = (
                f"🏗️ **BASE BUILDING — "
                f"ORDER #{order_id}**\n\n"
                f"👑 **Admin:** "
                f"`{minecraft_name}`\n\n"
                f"**Steps:**\n"
                f"1️⃣ Upload your schematic.\n"
                f"2️⃣ Discuss the build.\n"
                f"3️⃣ Negotiate the price.\n"
                f"4️⃣ Agree on the final price.\n"
                f"5️⃣ Follow payment instructions.\n"
                f"6️⃣ The build begins."
            )

        else:

            price = SERVICES.get(
                service,
                "See Admin",
            )

            message = (
                f"📍 **SERVICE PAYMENT — "
                f"ORDER #{order_id}**\n\n"
                f"🛠️ **Service:** {service}\n"
                f"👑 **Admin:** "
                f"`{minecraft_name}`\n"
                f"💰 **Price:** {price}\n\n"
                f"**Steps:**\n"
                f"1️⃣ TP to `{minecraft_name}` "
                f"if instructed.\n"
                f"2️⃣ Confirm the service.\n"
                f"3️⃣ Follow payment instructions.\n"
                f"4️⃣ The Admin completes the service."
            )

        await ctx.send(
            message
        )

        return

    await ctx.send(
        "❌ This is not an active ticket."
    )


# ============================================================
# AFK
# ============================================================

@bot.command(
    name="AFK"
)
async def afk(
    ctx,
    *,
    reason="No reason provided",
):

    if not await require_admin(ctx):
        return

    afk_admins[str(ctx.author.id)] = {
        "name": str(ctx.author),
        "reason": reason,
        "timestamp": int(
            time.time()
        ),
    }

    save_json(
        AFK_FILE,
        afk_admins,
    )

    await ctx.send(
        f"💤 **{ctx.author.display_name} is now AFK.**\n"
        f"Reason: {reason}"
    )


# ============================================================
# BACK
# ============================================================

@bot.command(
    name="Back"
)
async def back(ctx):

    if not await require_admin(ctx):
        return

    afk_admins.pop(
        str(ctx.author.id),
        None,
    )

    save_json(
        AFK_FILE,
        afk_admins,
    )

    await ctx.send(
        f"🟢 **{ctx.author.display_name} is back and available.**"
    )


# ============================================================
# ADMINS
# ============================================================

@bot.command(
    name="Admins"
)
async def admins_command(ctx):

    admins = get_admins(
        ctx.guild
    )

    if not admins:

        await ctx.send(
            "❌ No Admins found."
        )

        return

    embed = discord.Embed(
        title="👑 ADMIN TEAM",
        color=discord.Color.gold(),
    )

    available = []
    afk = []

    for admin in admins:

        if str(admin.id) in afk_admins:

            reason = afk_admins[
                str(admin.id)
            ].get(
                "reason",
                "No reason",
            )

            afk.append(
                f"💤 {admin.mention} — {reason}"
            )

        else:

            available.append(
                f"🟢 {admin.mention}"
            )

    if available:

        embed.add_field(
            name="🟢 AVAILABLE",
            value="\n".join(
                available
            ),
            inline=False,
        )

    if afk:

        embed.add_field(
            name="💤 AFK",
            value="\n".join(
                afk
            ),
            inline=False,
        )

    await ctx.send(
        embed=embed
    )


# ============================================================
# PAYMENT
# ============================================================

@bot.command(
    name="Payment"
)
async def payment(
    ctx,
    amount=None,
    *,
    minecraft_name=None,
):

    if not await require_admin(ctx):
        return

    if amount is None or minecraft_name is None:

        await ctx.send(
            "### 💳 Payment Commands\n\n"
            "`!Payment <Amount> <User>`\n"
            "Example: `!Payment 15m Ryusaki`\n\n"
            "`!Payment Complete <User>`\n"
            "Completes and removes an active payment."
        )

        return

    minecraft_name = minecraft_name.strip()

    # COMPLETE
    if amount.lower() == "complete":

        name_key = minecraft_name

        if name_key not in payments:

            # Case-insensitive lookup
            found_key = None

            for existing_name in payments:

                if (
                    existing_name.lower()
                    == name_key.lower()
                ):

                    found_key = existing_name
                    break

            if found_key:
                name_key = found_key

        if name_key not in payments:

            await ctx.send(
                f"❌ No active payment found for "
                f"**{minecraft_name}**."
            )

            return

        old_payment = payments[
            name_key
        ]

        history_entry = {
            "user": name_key,
            "amount": old_payment.get(
                "amount"
            ),
            "amount_numeric": old_payment.get(
                "amount_numeric",
                0,
            ),
            "recorded_by": old_payment.get(
                "admin",
                "Unknown",
            ),
            "completed_by": str(
                ctx.author
            ),
            "timestamp": int(
                time.time()
            ),
        }

        payment_history.append(
            history_entry
        )

        del payments[
            name_key
        ]

        save_json(
            PAYMENTS_FILE,
            payments,
        )

        save_json(
            PAYMENT_HISTORY_FILE,
            payment_history,
        )

        numeric_amount = old_payment.get(
            "amount_numeric",
            0,
        )

        add_admin_stat(
            ctx.author,
            "payments_handled",
        )

        add_admin_stat(
            ctx.author,
            "revenue_handled",
            numeric_amount,
        )

        await ctx.send(
            f"✅ Payment completed for "
            f"**{name_key}**.\n"
            f"💰 Amount: "
            f"**{old_payment.get('amount')}**\n"
            f"🗑️ Removed from active tracker."
        )

        return

    # ADD PAYMENT
    numeric_amount = parse_amount(
        amount
    )

    if numeric_amount is None:

        await ctx.send(
            "❌ Invalid amount.\n"
            "Examples: `15m`, `2.5b`, `1000000`"
        )

        return

    # Duplicate protection
    for existing_name, existing in payments.items():

        if (
            existing_name.lower()
            == minecraft_name.lower()
        ):

            await ctx.send(
                f"⚠️ **{existing_name}** "
                f"already has an active payment.\n\n"
                f"💰 Current amount: "
                f"**{existing.get('amount')}**\n"
                f"👑 Recorded by: "
                f"**{existing.get('admin')}**\n\n"
                f"Use:\n"
                f"`!Payment Complete {existing_name}`"
            )

            return

    payments[minecraft_name] = {
        "amount": amount,
        "amount_numeric": numeric_amount,
        "admin": str(
            ctx.author
        ),
        "admin_id": ctx.author.id,
        "timestamp": int(
            time.time()
        ),
    }

    save_json(
        PAYMENTS_FILE,
        payments,
    )

    await ctx.send(
        f"✅ **Payment added to tracker.**\n\n"
        f"👤 **User:** {minecraft_name}\n"
        f"💰 **Amount:** {amount}\n"
        f"👑 **Recorded by:** "
        f"{ctx.author.mention}"
    )


# ============================================================
# TRACK PAYMENTS
# ============================================================

@bot.command(
    name="Track"
)
async def track(ctx):

    if not await require_admin(ctx):
        return

    if not payments:

        await ctx.send(
            "📊 **Payment Tracker**\n\n"
            "No payments are currently being tracked."
        )

        return

    embed = discord.Embed(
        title="📊 ACTIVE PAYMENTS",
        color=discord.Color.gold(),
    )

    total = 0

    for minecraft_name, data in payments.items():

        numeric_amount = data.get(
            "amount_numeric",
            parse_amount(
                data.get(
                    "amount",
                    0,
                )
            ) or 0,
        )

        total += numeric_amount

        embed.add_field(
            name=f"👤 {minecraft_name}",
            value=(
                f"💰 Amount: "
                f"**{data.get('amount')}**\n"
                f"👑 Recorded by: "
                f"**{data.get('admin')}**"
            ),
            inline=False,
        )

    embed.add_field(
        name="💰 ACTIVE TOTAL",
        value=format_amount(
            total
        ),
        inline=False,
    )

    await ctx.send(
        embed=embed
    )


# ============================================================
# PAYMENT HISTORY
# ============================================================

@bot.command(
    name="PaymentHistory"
)
async def payment_history_command(ctx):

    if not await require_admin(ctx):
        return

    if not payment_history:

        await ctx.send(
            "📜 No completed payments have been recorded yet."
        )

        return

    embed = discord.Embed(
        title="📜 PAYMENT HISTORY",
        color=discord.Color.blue(),
    )

    for payment_data in reversed(
        payment_history[-20:]
    ):

        user = payment_data.get(
            "user",
            "Unknown",
        )

        amount = payment_data.get(
            "amount",
            "Unknown",
        )

        completed_by = payment_data.get(
            "completed_by",
            "Unknown",
        )

        embed.add_field(
            name=f"👤 {user}",
            value=(
                f"💰 {amount}\n"
                f"👑 Completed by: {completed_by}"
            ),
            inline=False,
        )

    await ctx.send(
        embed=embed
    )


# ============================================================
# REVENUE
# ============================================================

@bot.command(
    name="Revenue"
)
async def revenue(ctx):

    if not await require_admin(ctx):
        return

    now = datetime.now(
        timezone.utc
    )

    today_total = 0
    week_total = 0
    all_time = 0

    today_date = now.date()

    week_start = (
        now - timedelta(days=7)
    ).timestamp()

    for payment_data in payment_history:

        amount = int(
            payment_data.get(
                "amount_numeric",
                0,
            )
        )

        timestamp = payment_data.get(
            "timestamp",
            0,
        )

        all_time += amount

        payment_date = datetime.fromtimestamp(
            timestamp,
            timezone.utc,
        ).date()

        if payment_date == today_date:
            today_total += amount

        if timestamp >= week_start:
            week_total += amount

    embed = discord.Embed(
        title="💰 REVENUE STATISTICS",
        color=discord.Color.green(),
    )

    embed.add_field(
        name="📅 Today",
        value=format_amount(
            today_total
        ),
        inline=True,
    )

    embed.add_field(
        name="📆 Last 7 Days",
        value=format_amount(
            week_total
        ),
        inline=True,
    )

    embed.add_field(
        name="💎 All Time",
        value=format_amount(
            all_time
        ),
        inline=True,
    )

    embed.add_field(
        name="💳 Completed Transactions",
        value=str(
            len(payment_history)
        ),
        inline=False,
    )

    await ctx.send(
        embed=embed
    )


# ============================================================
# ADMIN STATS
# ============================================================

@bot.command(
    name="AdminStats"
)
async def admin_stats_command(ctx):

    if not await require_admin(ctx):
        return

    if not admin_stats:

        await ctx.send(
            "📊 No Admin statistics have been recorded yet."
        )

        return

    embed = discord.Embed(
        title="👑 ADMIN STATISTICS",
        color=discord.Color.gold(),
    )

    for admin_id, data in admin_stats.items():

        review_list = data.get(
            "reviews",
            [],
        )

        if review_list:

            average = (
                sum(review_list)
                / len(review_list)
            )

            average_text = (
                f"{average:.2f}/5"
            )

        else:

            average_text = "No reviews"

        embed.add_field(
            name=f"👑 {data.get('name', 'Unknown')}",
            value=(
                f"🎫 Tickets completed: "
                f"**{data.get('tickets_completed', 0)}**\n"
                f"💳 Payments handled: "
                f"**{data.get('payments_handled', 0)}**\n"
                f"💰 Revenue handled: "
                f"**{format_amount(data.get('revenue_handled', 0))}**\n"
                f"⭐ Rating: "
                f"**{average_text}**"
            ),
            inline=False,
        )

    await ctx.send(
        embed=embed
    )


# ============================================================
# REVIEWS
# ============================================================

@bot.command(
    name="Reviews"
)
async def reviews_command(ctx):

    if not reviews:

        await ctx.send(
            "⭐ No reviews have been submitted yet."
        )

        return

    total = sum(
        review.get(
            "rating",
            0,
        )
        for review in reviews
    )

    average = (
        total
        / len(reviews)
    )

    embed = discord.Embed(
        title="⭐ CUSTOMER REVIEWS",
        description=(
            f"Average Rating: "
            f"**{average:.2f}/5**\n"
            f"Total Reviews: "
            f"**{len(reviews)}**"
        ),
        color=discord.Color.gold(),
    )

    for review in reversed(
        reviews[-10:]
    ):

        rating = int(
            review.get(
                "rating",
                0,
            )
        )

        embed.add_field(
            name=(
                f"{'⭐' * rating} "
                f"{review.get('user', 'Unknown')}"
            ),
            value=(
                f"Order: "
                f"#{review.get('order_id', 'Unknown')}\n"
                f"Admin: "
                f"{review.get('admin', 'Unknown')}"
            ),
            inline=False,
        )

    await ctx.send(
        embed=embed
    )


# ============================================================
# ORDER
# ============================================================

@bot.command(
    name="Order"
)
async def order(
    ctx,
    order_id=None,
):

    if not await require_admin(ctx):
        return

    if not order_id:

        await ctx.send(
            "Usage: `!Order <OrderID>`"
        )

        return

    order_data = orders.get(
        str(order_id)
    )

    if not order_data:

        await ctx.send(
            f"❌ Order **#{order_id}** was not found."
        )

        return

    embed = discord.Embed(
        title=f"🧾 ORDER #{order_id}",
        color=discord.Color.blue(),
    )

    for key, value in order_data.items():

        if key in (
            "id",
            "created",
            "completed_at",
            "closed_at",
        ):
            continue

        readable = (
            key
            .replace("_", " ")
            .title()
        )

        if (
            isinstance(value, int)
            and key in (
                "total",
                "price_per",
            )
        ):

            value = format_amount(
                value
            )

        embed.add_field(
            name=readable,
            value=str(value),
            inline=False,
        )

    await ctx.send(
        embed=embed
    )


# ============================================================
# TRANSCRIPT COMMAND
# ============================================================

@bot.command(
    name="Transcript"
)
async def transcript(ctx):

    if not await require_admin(ctx):
        return

    if not is_ticket_channel(
        ctx.channel
    ):

        await ctx.send(
            "❌ Use this command inside a ticket."
        )

        return

    success = await create_transcript(
        ctx.channel
    )

    if success:

        await ctx.send(
            "📜 Transcript saved."
        )

    else:

        await ctx.send(
            "❌ I could not create the transcript."
        )


# ============================================================
# COMMAND HELP / COMMAND CENTER
# ============================================================

@bot.command(
    name="h",
)
async def commands_list(ctx):


    embed = discord.Embed(
        title="📖 COMMAND CENTER",
        description=(
            "━━━━━━━━━━━━━━━━━━━━\n"
            "👑 **ADMIN COMMAND CENTER**\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "All commands are **case-insensitive**.\n"
            "`!commands`, `!Commands`, and "
            "`!COMMANDS` all work.\n\n"
            "Use the sections below to manage "
            "the entire shop."
        ),
        color=discord.Color.blurple(),
    )

    embed.add_field(
        name="🛒 SHOP",
        value=(
            "### `!SetupShop`\n"
            "Creates the main spawner shop panel "
            "with BUY and SELL buttons.\n\n"

            "### `!SetupTickets`\n"
            "Creates another spawner ticket panel.\n\n"

            "### `!Stock`\n"
            "Shows the current stock of every spawner.\n\n"

            "### `!Prices`\n"
            "Shows the current BUY and SELL prices."
        ),
        inline=False,
    )

    embed.add_field(
        name="📦 STOCK MANAGEMENT",
        value=(
            "### `!SetStock <Spawner> <Amount>`\n"
            "Changes the amount of a spawner in stock.\n"
            "Example: `!SetStock Skeleton 100`\n\n"

            "Spawner names are flexible:\n"
            "`Skeleton`, `Skelly`, `Skeletons`\n"
            "`Iron`, `IG`, `Iron Golem`\n"
            "`Creeper`, `Creepers`\n\n"

            "🔴 `0` = Out of stock\n"
            f"⚠️ `1-{LOW_STOCK_LIMIT}` = Low stock"
        ),
        inline=False,
    )

    embed.add_field(
        name="💰 PRICE MANAGEMENT",
        value=(
            "### `!ChangeBuyPrice <Spawner> <Price>`\n"
            "Changes the BUY price.\n"
            "Example: `!ChangeBuyPrice Skeleton 7m`\n\n"

            "### `!ChangeSellPrice <Spawner> <Price>`\n"
            "Changes the SELL price.\n"
            "Example: `!ChangeSellPrice Creeper 12m`\n\n"

            "Prices support `K`, `M`, and `B`.\n"
            "Example: `15m`, `2.5b`, `500k`."
        ),
        inline=False,
    )

    embed.add_field(
        name="🔥 DEALS",
        value=(
            "### `!RandomDeal`\n"
            "Creates a random discount of "
            "5%, 10%, 15%, 20%, or 25% "
            "on one random BUY spawner.\n\n"

            "### `!ClearDeal`\n"
            "Removes the active random deal."
        ),
        inline=False,
    )

    embed.add_field(
        name="🛠️ SERVICES",
        value=(
            "### `!SetupServices`\n"
            "Creates the Services panel.\n\n"

            "📍 **Low Cords — 15M**\n"
            "📍 **Mid Cords — 25M**\n"
            "📍 **Good Cords — 40M**\n"
            "📍 **God Cords — 50M**\n"
            "🏗️ **Base Building — Negotiable**\n"
            "⛏️ **Digging — Negotiable**\n\n"

            "Base Building and Digging are service tickets."
        ),
        inline=False,
    )

    embed.add_field(
        name="🎫 TICKETS",
        value=(
            "Tickets are created with the panel buttons.\n\n"

            "👑 **Claim** — Ticket manager claims the ticket.\n"
            "The claimant appears in the ticket scoreboard.\n\n"

            "🚨 **Priority** — Marks/unmarks a ticket "
            "as high priority.\n\n"

            "✅ **Complete** — Marks the order completed.\n\n"

            "🔒 **Close** — Saves a transcript and "
            "deletes the ticket.\n\n"

            "BUY stock is reserved when claimed. "
            "If the ticket closes without completion, "
            "the reservation is returned."
        ),
        inline=False,
    )

    embed.add_field(
        name="💳 PAYMENT",
        value=(
            "### `!Show <MinecraftName>`\n"
            "Shows payment/service instructions "
            "inside the active ticket.\n\n"
            "### `!Payment <Amount> <User>`\n"
            "Adds an active payment.\n"
            "Example: `!Payment 15m Ryusaki`\n\n"
            "### `!Payment Complete <User>`\n"
            "Completes the payment and moves it "
            "into payment history.\n\n"
            "### `!Track`\n"
            "Shows all active payments."
        ),
        inline=False,
    )

    embed.add_field(
        name="📊 PAYMENT & REVENUE",
        value=(
            "### `!PaymentHistory`\n"
            "Shows completed payment records.\n\n"

            "### `!Revenue`\n"
            "Shows today's revenue, last 7 days, "
            "and all-time revenue."
        ),
        inline=False,
    )

    embed.add_field(
        name="🧾 ORDERS",
        value=(
            "### `!Order <OrderID>`\n"
            "Shows information about a specific order.\n"
            "Example: `!Order 1001`\n\n"

            "Every ticket automatically receives "
            "a unique Order ID."
        ),
        inline=False,
    )

    embed.add_field(
        name="⭐ REVIEWS",
        value=(
            "### `!Reviews`\n"
            "Shows customer ratings and reviews.\n\n"

            "After an Admin completes a ticket, "
            "the customer receives a 1–5 star "
            "rating panel."
        ),
        inline=False,
    )

    embed.add_field(
        name="👑 ADMIN MANAGEMENT",
        value=(
            "### `!Admins`\n"
            "Shows Admins and whether they are "
            "available or AFK.\n\n"

            "### `!AFK <Reason>`\n"
            "Marks yourself AFK.\n"
            "Example: `!AFK Eating dinner`\n\n"

            "### `!Back`\n"
            "Marks yourself available again.\n\n"

            "### `!AdminStats`\n"
            "Shows tickets completed, payments handled, "
            "revenue handled, and ratings."
        ),
        inline=False,
    )

    embed.add_field(
        name="👤 ADMIN DISPLAY",
        value=(
            "### `!Ign @User <MinecraftName>`\n"
            "Assigns a Minecraft username to a Discord member.\n\n"
            "Example:\n"
            "`!Ign @User Cadley`"
        ),
        inline=False,
    )

    embed.add_field(
        name="📜 TRANSCRIPTS",
        value=(
            "### `!Transcript`\n"
            "Manually saves the current ticket "
            "conversation to the transcript channel.\n\n"

            "Closing a ticket automatically creates "
            "a transcript first."
        ),
        inline=False,
    )

    embed.add_field(
        name="🛡️ MODERATION",
        value=(
            "### `!ban <@User> [reason]`\n"
            "Bans a member. Admin-only.\n\n"

            "### `!timeout <@User> <time> [reason]`\n"
            "Times out a member. Admin-only.\n"
            "Examples: `10m`, `2h`, `1d`.\n\n"

            "### AUTOMATIC ANTI-SPAM\n"
            "10 messages in 10 seconds = warning.\n"
            "Repeat it = 1-minute timeout.\n"
            "Repeat again within 1 hour = 2-hour timeout."
        ),
        inline=False,
    ),

    embed.add_field(
        name="⚙️ SYSTEM FEATURES",
        value=(
            "✅ Persistent buttons\n"
            "✅ Case-insensitive commands\n"
            "✅ One open ticket per customer\n"
            "✅ Ticket cooldown\n"
            "✅ Admin ping\n"
            "✅ Dynamic Admin claiming\n"
            "✅ BUY stock reservation\n"
            "✅ Stock restoration\n"
            "✅ SELL stock addition\n"
            "✅ Low-stock warnings\n"
            "✅ Automatic shop updates\n"
            "✅ Order IDs\n"
            "✅ Payment duplicate protection\n"
            "✅ Payment history\n"
            "✅ Revenue tracking\n"
            "✅ Customer reviews\n"
            "✅ Admin statistics\n"
            "✅ Ticket transcripts"
        ),
        inline=False,
    )

    embed.set_footer(
        text=(
            "Spawner & Services Bot • "
            "Admin Command Center • "
            "All commands are case-insensitive"
        )
    )

    await ctx.send(
        embed=embed
    )


# ============================================================
# MODERATION
# ============================================================

def parse_duration(value):
    if not value:
        return None

    match = re.fullmatch(
        r"(\d+(?:\.\d+)?)([smhdw])",
        str(value).strip().lower(),
    )

    if not match:
        return None

    amount = float(match.group(1))
    unit = match.group(2)

    multipliers = {
        "s": 1,
        "m": 60,
        "h": 60 * 60,
        "d": 60 * 60 * 24,
        "w": 60 * 60 * 24 * 7,
    }

    return int(amount * multipliers[unit])


def moderation_target_is_admin(member):
    return (
        member.guild_permissions.administrator
        or any(
            role.name.lower() == ADMIN_ROLE_NAME.lower()
            for role in member.roles
        )
    )


async def send_moderation_dm(member, title, message):
    try:
        embed = discord.Embed(
            title=title,
            description=message,
            color=discord.Color.red(),
        )
        await member.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        pass


@bot.command(
    name="ban"
)
async def ban_command(
    ctx,
    member: discord.Member = None,
    *,
    reason=None,
):

    if not await require_admin(ctx):
        return

    if member is None:
        await ctx.send(
            "Usage: `!ban @User [reason]`"
        )
        return

    if member == ctx.author:
        await ctx.send(
            "❌ You cannot ban yourself."
        )
        return

    if member == ctx.guild.owner:
        await ctx.send(
            "❌ You cannot ban the server owner."
        )
        return

    if moderation_target_is_admin(member):
        await ctx.send(
            "❌ You cannot ban another Admin."
        )
        return

    if not ctx.guild.me.guild_permissions.ban_members:
        await ctx.send(
            "❌ I do not have the **Ban Members** permission."
        )
        return

    reason = reason or f"Banned by {ctx.author}"

    await send_moderation_dm(
        member,
        "🔨 You have been banned",
        f"You were banned from **{ctx.guild.name}**.\n\n"
        f"Reason: **{reason}**",
    )

    try:
        await member.ban(
            reason=reason,
            delete_message_seconds=0,
        )
    except discord.Forbidden:
        await ctx.send(
            "❌ I cannot ban that user. Check my role position and permissions."
        )
        return

    await ctx.send(
        f"🔨 **{member}** has been banned.\n"
        f"Reason: **{reason}**"
    )


@bot.command(
    name="timeout"
)
async def timeout_command(
    ctx,
    member: discord.Member = None,
    duration=None,
    *,
    reason=None,
):

    if not await require_admin(ctx):
        return

    if member is None or duration is None:
        await ctx.send(
            "Usage: `!timeout @User <time> [reason]`\n"
            "Examples: `!timeout @User 10m`, `!timeout @User 2h`"
        )
        return

    seconds = parse_duration(duration)

    if seconds is None or seconds <= 0:
        await ctx.send(
            "❌ Invalid time. Use `30s`, `10m`, `2h`, `1d`, or `1w`."
        )
        return

    max_timeout = 28 * 24 * 60 * 60

    if seconds > max_timeout:
        await ctx.send(
            "❌ Discord allows a maximum timeout of 28 days."
        )
        return

    if member == ctx.author:
        await ctx.send(
            "❌ You cannot timeout yourself."
        )
        return

    if member == ctx.guild.owner:
        await ctx.send(
            "❌ You cannot timeout the server owner."
        )
        return

    if moderation_target_is_admin(member):
        await ctx.send(
            "❌ You cannot timeout another Admin."
        )
        return

    if not ctx.guild.me.guild_permissions.moderate_members:
        await ctx.send(
            "❌ I do not have the **Moderate Members** permission."
        )
        return

    reason = reason or f"Timed out by {ctx.author}"

    until = discord.utils.utcnow() + timedelta(seconds=seconds)

    try:
        await member.timeout(
            until,
            reason=reason,
        )
    except discord.Forbidden:
        await ctx.send(
            "❌ I cannot timeout that user. Check my role position and permissions."
        )
        return

    await send_moderation_dm(
        member,
        "⏱️ You have been timed out",
        f"You were timed out in **{ctx.guild.name}** for **{duration}**.\n\n"
        f"Reason: **{reason}**",
    )

    await ctx.send(
        f"⏱️ **{member}** has been timed out for **{duration}**.\n"
        f"Reason: **{reason}**"
    )


async def handle_spam(message):
    if not message.guild:
        return

    member = message.author

    if moderation_target_is_admin(member):
        return

    now = time.time()
    user_key = (message.guild.id, member.id)
    timestamps = spam_message_times[user_key]

    while timestamps and now - timestamps[0] > SPAM_WINDOW_SECONDS:
        timestamps.popleft()

    timestamps.append(now)

    if len(timestamps) < SPAM_MESSAGE_LIMIT:
        return

    timestamps.clear()

    escalation = spam_escalation.get(user_key)
    previous_action = escalation.get("action") if escalation else 0
    previous_time = escalation.get("timestamp", 0) if escalation else 0

    if previous_action >= 1 and now - previous_time <= SPAM_ESCALATION_WINDOW_SECONDS:
        timeout_seconds = SPAM_SECOND_TIMEOUT_SECONDS
        action_number = 2
    else:
        timeout_seconds = SPAM_FIRST_TIMEOUT_SECONDS
        action_number = 1

    spam_escalation[user_key] = {
        "action": action_number,
        "timestamp": now,
    }

    if not message.guild.me.guild_permissions.moderate_members:
        await message.channel.send(
            f"{member.mention} ⚠️ Stop spamming. I do not have permission to timeout members.",
            delete_after=10,
        )
        return

    if action_number == 1:
        await message.channel.send(
            f"{member.mention} ⚠️ **Stop spamming.** 10 messages in 10 seconds detected. Do it again and you will be timed out for **1 minute**.",
            delete_after=10,
        )
        dm_title = "⚠️ Spam warning"
        dm_text = (
            f"You sent 10 messages within 10 seconds in **{message.guild.name}**.\n\n"
            "This is your warning. If you repeat the spam, you will be timed out for 1 minute."
        )
    else:
        dm_title = "⏱️ Spam timeout"
        dm_text = (
            f"You repeated the spam violation in **{message.guild.name}** within 1 hour of your previous warning.\n\n"
            "You have been timed out for 2 hours."
        )

    try:
        until = discord.utils.utcnow() + timedelta(seconds=timeout_seconds)
        await member.timeout(
            until,
            reason="Automatic anti-spam moderation",
        )

        await send_moderation_dm(
            member,
            dm_title,
            dm_text,
        )

        if action_number == 2:
            await message.channel.send(
                f"{member.mention} ⏱️ **2-hour timeout** for repeated spam.",
                delete_after=10,
            )

    except discord.Forbidden:
        await message.channel.send(
            f"{member.mention} ⚠️ Stop spamming. I could not apply the automatic timeout because of my permissions.",
            delete_after=10,
        )

# ============================================================
# UNKNOWN COMMAND / ERROR HANDLER
# ============================================================

@bot.event
async def on_command_error(
    ctx,
    error,
):

    if isinstance(
        error,
        commands.CommandNotFound,
    ):
        return

    if isinstance(
        error,
        commands.MissingRequiredArgument,
    ):

        await ctx.send(
            "❌ Missing an argument.\n"
            "Use `!Commands` to see the full command guide.",
            delete_after=10,
        )

        return

    if isinstance(
        error,
        commands.BadArgument,
    ):

        await ctx.send(
            "❌ Invalid argument.\n"
            "Use `!Commands` for command examples.",
            delete_after=10,
        )

        return

    print(
        f"Command error in {ctx.command}: {error}"
    )


# ============================================================
# MESSAGE HANDLER
# ============================================================

@bot.event
async def on_message(
    message
):

    if message.author.bot:
        return

    await handle_spam(
        message
    )

    await bot.process_commands(
        message
    )


# ============================================================
# READY
# ============================================================

@bot.event
async def on_ready():

    print(
        "=============================================="
    )

    print(
        f"Logged in as: {bot.user}"
    )

    print(
        f"Bot ID: {bot.user.id}"
    )

    print(
        "Spawner + Services Bot is ONLINE."
    )

    print(
        "Commands are case-insensitive."
    )

    print(
        "Persistent ticket buttons loaded."
    )

    print(
        "=============================================="
    )


# ============================================================
# PERSISTENT VIEWS
# ============================================================

async def setup_persistent_views():

    bot.add_view(
        SpawnerPanelView()
    )

    bot.add_view(
        ServicePanelView()
    )

    bot.add_view(
        TicketControlView()
    )

    bot.add_view(
        ServiceTicketControlView()
    )


# ============================================================
# MAIN
# ============================================================

async def main():

    if not TOKEN or TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":

        print(
            "ERROR: You need to put your Discord bot token "
            "in the TOKEN variable."
        )

        return

    await setup_persistent_views()

    await bot.start(
        TOKEN
    )


if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print(
            "Bot stopped."
        )