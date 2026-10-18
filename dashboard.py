"""Webdashboard voor de bot. Draait in hetzelfde proces als de bot.

Inloggen gaat via Discord OAuth2. Alleen een Discord-account met een
geverifieerd e-mailadres uit ADMIN_EMAILS krijgt toegang.
"""
import contextvars
import datetime as dt
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

import discord
from aiohttp import ClientSession, web
from discord import app_commands

ADMIN_EMAILS = {e.strip().lower() for e in
                os.getenv("ADMIN_EMAILS", "matteocleys@gmail.com").split(",") if e.strip()}
ADMIN_USERNAMES = {e.strip().lower() for e in
                   os.getenv("ADMIN_USERNAMES", "bloempitbull").split(",") if e.strip()}
ADMIN_IDS = {e.strip() for e in os.getenv("ADMIN_USER_IDS", "").split(",") if e.strip()}
current = contextvars.ContextVar("current", default=None)
CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
_cs, _dom = os.getenv("CODESPACE_NAME"), os.getenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN")
_default = (f"https://{_cs}-{os.getenv('PORT', '8080')}.{_dom}" if _cs and _dom
            else "http://localhost:8080")  # in GitHub Codespaces vindt hij zijn eigen adres
BASE = os.getenv("DASHBOARD_URL", _default).rstrip("/")
HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))
COOKIE = "dash_session"
SESSION_SECONDS = 12 * 3600

PERMS = ["administrator", "manage_guild", "manage_roles", "manage_channels", "kick_members",
         "ban_members", "moderate_members", "manage_messages", "mention_everyone",
         "view_channel", "send_messages", "connect", "speak"]

sessions: dict[str, dict] = {}
states: dict[str, float] = {}


def bad(msg: str, status=400):
    cls = {400: web.HTTPBadRequest, 403: web.HTTPForbidden, 404: web.HTTPNotFound}[status]
    return cls(text=json.dumps({"error": msg}), content_type="application/json")


async def start_dashboard(bot, cfg, save, data, log):
    if not CLIENT_ID or not CLIENT_SECRET:
        print("Dashboard staat uit: zet DISCORD_CLIENT_ID en DISCORD_CLIENT_SECRET.")
        return

    routes = web.RouteTableDef()

    def guild_of(value) -> discord.Guild:
        g = bot.get_guild(int(value))
        s = current.get()
        if not g or not s or g.id not in s["guilds"]:  # alleen servers waar de ingelogde persoon ook in zit
            raise bad("Server niet gevonden", 404)
        return g

    def ticket_of(g, cid) -> discord.TextChannel:
        ch = g.get_channel(int(cid))
        if not isinstance(ch, discord.TextChannel) or not (ch.topic or "").startswith("ticket:"):
            raise bad("Dat is geen ticket", 404)
        return ch

    def role_of(g, rid) -> discord.Role:
        r = g.get_role(int(rid))
        if not r or r.is_default() or r.managed:
            raise bad("Deze rol kan niet bewerkt worden")
        return r

    def js(obj):
        return web.json_response(obj)

    def color_of(hexstr: str) -> discord.Colour:
        return discord.Colour(int(hexstr.lstrip("#"), 16))

    def perms_of(lst) -> discord.Permissions:
        return discord.Permissions(**{p: True for p in lst if p in PERMS})

    # ---------------- middleware ----------------
    @web.middleware
    async def mw(req, handler):
        if req.path.startswith("/api/"):
            s = sessions.get(req.cookies.get(COOKIE, ""))
            if not s or s["exp"] < time.time():
                return web.json_response({"error": "Niet ingelogd"}, status=401)
            if req.method == "POST" and req.content_type != "application/json":
                return web.json_response({"error": "Ongeldig verzoek"}, status=400)
            req["user"] = s
            current.set(s)
        try:
            resp = await handler(req)
        except discord.Forbidden:
            resp = web.json_response({"error": "De bot mag dit niet (staat de bot-rol hoog genoeg?)"}, status=403)
        except discord.HTTPException as e:
            resp = web.json_response({"error": f"Discord-fout: {e.text}"}, status=400)
        except (ValueError, KeyError, TypeError):
            resp = web.json_response({"error": "Ongeldige invoer"}, status=400)
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    # ---------------- login ----------------
    @routes.get("/")
    async def index(req):
        return web.FileResponse(Path(__file__).with_name("dashboard.html"))

    @routes.get("/login")
    async def login(req):
        now = time.time()
        for k in [k for k, t in states.items() if now - t > 600]:
            states.pop(k, None)
        state = secrets.token_urlsafe(16)
        states[state] = now
        raise web.HTTPFound("https://discord.com/oauth2/authorize?" + urlencode({
            "client_id": CLIENT_ID, "redirect_uri": BASE + "/callback",
            "response_type": "code", "scope": "identify email guilds", "state": state}))

    @routes.get("/callback")
    async def callback(req):
        code, state = req.query.get("code"), req.query.get("state")
        if not code or states.pop(state, None) is None:
            return web.Response(text="Ongeldige of verlopen login. Probeer opnieuw.", status=400)
        async with ClientSession() as http:
            async with http.post("https://discord.com/api/oauth2/token", data={
                    "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "grant_type": "authorization_code",
                    "code": code, "redirect_uri": BASE + "/callback"}) as r:
                tok = await r.json()
            if "access_token" not in tok:
                return web.Response(text="Login mislukt.", status=400)
            async with http.get("https://discord.com/api/users/@me",
                                headers={"Authorization": "Bearer " + tok["access_token"]}) as r:
                u = await r.json()
            async with http.get("https://discord.com/api/users/@me/guilds",
                                headers={"Authorization": "Bearer " + tok["access_token"]}) as r:
                gl = await r.json()
        email = (u.get("email") or "").lower() if u.get("verified") else ""
        is_admin = (email in ADMIN_EMAILS or str(u["id"]) in ADMIN_IDS
                    or u["username"].lower() in ADMIN_USERNAMES)
        if not is_admin:
            return web.Response(text="Geen toegang: dit Discord-account is geen beheerder van het dashboard.",
                                status=403)
        sid = secrets.token_urlsafe(32)
        sessions[sid] = {"name": u.get("global_name") or u["username"], "exp": time.time() + SESSION_SECONDS,
                         "guilds": {int(x["id"]) for x in gl} if isinstance(gl, list) else set()}
        resp = web.HTTPFound("/")
        resp.set_cookie(COOKIE, sid, httponly=True, samesite="Lax", max_age=SESSION_SECONDS,
                        secure=BASE.startswith("https"))
        raise resp

    @routes.post("/api/logout")
    async def logout(req):
        sessions.pop(req.cookies.get(COOKIE, ""), None)
        return js({"ok": True})

    @routes.get("/api/me")
    async def me(req):
        return js({"name": req["user"]["name"]})

    @routes.get("/api/guilds")
    async def guilds(req):
        return js([{"id": str(g.id), "name": g.name, "icon": g.icon.url if g.icon else None}
                   for g in bot.guilds if g.id in req["user"]["guilds"]])

    # ---------------- 1. statistieken ----------------
    @routes.get("/api/stats")
    async def stats(req):
        g = guild_of(req.query["guild"])
        st = data.get("_stats", {"uses": {}, "daily": {}})
        today = discord.utils.utcnow().strftime("%Y-%m-%d")
        n_cmds = sum(1 for c in bot.tree.walk_commands() if isinstance(c, app_commands.Command))
        return js({
            "commands_total": n_cmds, "uses_total": sum(st["uses"].values()),
            "uses_today": st["daily"].get(today, 0), "servers": len(bot.guilds),
            "members": g.member_count, "ping": round(bot.latency * 1000),
            "open_tickets": sum(1 for c in g.text_channels if (c.topic or "").startswith("ticket:")),
            "uptime": int(time.time() - bot.started),
            "top": sorted(st["uses"].items(), key=lambda x: -x[1])[:10],
            "daily": sorted(st["daily"].items())[-14:]})

    # ---------------- 3. commando's aan/uit ----------------
    @routes.get("/api/commands")
    async def commands_list(req):
        g = guild_of(req.query["guild"])
        off = cfg(g.id)["disabled"]
        uses = data.get("_stats", {}).get("uses", {})
        return js([{"name": c.name, "desc": c.description, "enabled": c.name not in off,
                    "uses": sum(v for k, v in uses.items() if k.split()[0] == c.name)}
                   for c in bot.tree.get_commands()])

    @routes.post("/api/commands/toggle")
    async def commands_toggle(req):
        d = await req.json()
        g = guild_of(d["guild"])
        name = d["name"]
        if name not in {c.name for c in bot.tree.get_commands()}:
            raise bad("Onbekend commando")
        off = cfg(g.id)["disabled"]
        if d["enabled"] and name in off:
            off.remove(name)
        elif not d["enabled"] and name not in off:
            off.append(name)
        save()
        return js({"ok": True})

    # ---------------- 2. tickets ----------------
    @routes.get("/api/tickets")
    async def tickets(req):
        g = guild_of(req.query["guild"])
        out = []
        for c in g.text_channels:
            if (c.topic or "").startswith("ticket:"):
                owner = g.get_member(int(c.topic.split(":")[1]))
                out.append({"id": str(c.id), "name": c.name, "owner": owner.display_name if owner else "?"})
        return js(out)

    @routes.get("/api/tickets/{cid}/messages")
    async def ticket_messages(req):
        ch = ticket_of(guild_of(req.query["guild"]), req.match_info["cid"])
        out = []
        async for m in ch.history(limit=50):
            text = m.content or (m.embeds[0].description if m.embeds and m.embeds[0].description else "")
            if m.attachments:
                text += "\n" + "\n".join(a.url for a in m.attachments)
            out.append({"author": m.author.display_name, "bot": m.author.bot, "content": text,
                        "time": m.created_at.strftime("%d-%m %H:%M")})
        return js(out[::-1])

    @routes.post("/api/tickets/{cid}/reply")
    async def ticket_reply(req):
        d = await req.json()
        ch = ticket_of(guild_of(d["guild"]), req.match_info["cid"])
        text = str(d["content"]).strip()
        if not text:
            raise bad("Leeg bericht")
        await ch.send(f"**Support ({req['user']['name']}):** {text}"[:2000],
                      allowed_mentions=discord.AllowedMentions.none())
        return js({"ok": True})

    @routes.post("/api/tickets/{cid}/close")
    async def ticket_close(req):
        d = await req.json()
        g = guild_of(d["guild"])
        ch = ticket_of(g, req.match_info["cid"])
        await log(g, "Ticket gesloten (dashboard)", f"#{ch.name} door {req['user']['name']}")
        await ch.delete(reason=f"Dashboard: {req['user']['name']}")
        return js({"ok": True})

    # ---------------- 4. rollen ----------------
    def role_json(r: discord.Role):
        return {"id": str(r.id), "name": r.name, "color": f"#{r.color.value:06x}", "hoist": r.hoist,
                "mentionable": r.mentionable, "managed": r.managed, "members": len(r.members),
                "perms": [p for p in PERMS if getattr(r.permissions, p)]}

    @routes.get("/api/roles")
    async def roles(req):
        g = guild_of(req.query["guild"])
        rs = [r for r in reversed(g.roles) if not r.is_default()]
        return js({"roles": [role_json(r) for r in rs], "perms": PERMS})

    @routes.post("/api/roles/save")
    async def roles_save(req):
        d = await req.json()
        g = guild_of(d["guild"])
        kw = dict(name=str(d["name"])[:100], colour=color_of(d["color"]), hoist=bool(d["hoist"]),
                  mentionable=bool(d["mentionable"]), permissions=perms_of(d["perms"]))
        if d.get("id"):
            await role_of(g, d["id"]).edit(**kw, reason=f"Dashboard: {req['user']['name']}")
        else:
            await g.create_role(**kw, reason=f"Dashboard: {req['user']['name']}")
        return js({"ok": True})

    @routes.post("/api/roles/delete")
    async def roles_delete(req):
        d = await req.json()
        await role_of(guild_of(d["guild"]), d["id"]).delete(reason=f"Dashboard: {req['user']['name']}")
        return js({"ok": True})

    # ---------------- extra: leden ----------------
    @routes.get("/api/members")
    async def members(req):
        g = guild_of(req.query["guild"])
        q = req.query.get("q", "").strip()
        if not q:
            raise ValueError
        ms = await g.query_members(user_ids=[int(q)]) if q.isdigit() else await g.query_members(q, limit=10)
        return js([{"id": str(m.id), "name": str(m), "display": m.display_name,
                    "roles": [str(r.id) for r in m.roles if not r.is_default()],
                    "muted": m.is_timed_out()} for m in ms])

    @routes.post("/api/members/role")
    async def members_role(req):
        d = await req.json()
        g = guild_of(d["guild"])
        m = await g.fetch_member(int(d["user"]))
        r = role_of(g, d["role"])
        reason = f"Dashboard: {req['user']['name']}"
        await (m.add_roles(r, reason=reason) if d["add"] else m.remove_roles(r, reason=reason))
        return js({"ok": True})

    @routes.post("/api/members/action")
    async def members_action(req):
        d = await req.json()
        g = guild_of(d["guild"])
        act = d["action"]
        reason = f"Dashboard ({req['user']['name']}): {str(d.get('reason') or '-')[:200]}"
        if act == "unban":
            await g.unban(discord.Object(int(d["user"])), reason=reason)
        else:
            m = await g.fetch_member(int(d["user"]))
            if act == "kick":
                await m.kick(reason=reason)
            elif act == "ban":
                await m.ban(reason=reason, delete_message_days=0)
            elif act == "mute":
                await m.timeout(dt.timedelta(minutes=max(1, min(int(d.get("minutes", 10)), 40320))), reason=reason)
            elif act == "unmute":
                await m.timeout(None, reason=reason)
            else:
                raise bad("Onbekende actie")
        await log(g, f"Dashboard: {act}", f"Gebruiker {d['user']}\nDoor: {req['user']['name']}\n{reason}")
        return js({"ok": True})

    # ---------------- extra: instellingen ----------------
    @routes.get("/api/settings")
    async def settings_get(req):
        g = guild_of(req.query["guild"])
        c = cfg(g.id)
        nm = lambda items: [{"id": str(i.id), "name": i.name} for i in items]
        return js({"log_channel": c["log_channel"] and str(c["log_channel"]),
                   "welcome_channel": c["welcome_channel"] and str(c["welcome_channel"]),
                   "ticket_category": c["ticket_category"] and str(c["ticket_category"]),
                   "support_role": c["support_role"] and str(c["support_role"]),
                   "antiraid": c["antiraid"], "channels": nm(g.text_channels),
                   "categories": nm(g.categories), "roles": nm(r for r in g.roles if not r.is_default())})

    @routes.post("/api/settings")
    async def settings_set(req):
        d = await req.json()
        g = guild_of(d["guild"])
        c = cfg(g.id)
        for k in ("log_channel", "welcome_channel", "ticket_category", "support_role"):
            c[k] = int(d[k]) if d.get(k) else None
        a, n = c["antiraid"], d["antiraid"]
        a["enabled"] = bool(n["enabled"])
        a["joins"] = max(2, min(int(n["joins"]), 50))
        a["seconds"] = max(2, min(int(n["seconds"]), 120))
        a["min_age_days"] = max(0, min(int(n["min_age_days"]), 365))
        a["action"] = "ban" if n["action"] == "ban" else "kick"
        save()
        return js({"ok": True})

    # ---------------- extra: aankondiging ----------------
    @routes.post("/api/announce")
    async def announce(req):
        d = await req.json()
        g = guild_of(d["guild"])
        ch = g.get_channel(int(d["channel"]))
        if not isinstance(ch, discord.TextChannel):
            raise bad("Kanaal niet gevonden")
        e = discord.Embed(title=str(d["title"])[:250], description=str(d["message"])[:3500],
                          color=discord.Color.gold(), timestamp=discord.utils.utcnow())
        e.set_footer(text=f"Door {req['user']['name']}")
        content = {"everyone": "@everyone", "here": "@here"}.get(d.get("ping"))
        await ch.send(content=content, embed=e, allowed_mentions=discord.AllowedMentions(everyone=True))
        return js({"ok": True})

    app = web.Application(middlewares=[mw])
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, HOST, PORT).start()
    print(f"Dashboard draait op {BASE} (poort {PORT})")
