# Discord bot (Nederlands)

Slash-commands: algemeen, moderatie (kick/ban/unban/mute/unmute/warn/clear/slowmode/lock),
tickets, aankondigingen, anti-raid, uitnodigingen, welkomstbericht en logs.

## 1. Bot aanmaken
1. Ga naar https://discord.com/developers/applications → **New Application**.
2. Tab **Bot** → **Reset Token** → kopieer de token (nooit delen!).
3. Zet op dezelfde pagina **Server Members Intent** aan (nodig voor anti-raid/welkom).
4. Start de bot (zie hieronder) en typ `/invite` voor de uitnodigingslink, of maak er zelf een
   via **OAuth2 → URL Generator** (scopes: `bot` + `applications.commands`).
5. Zet in je server de rol van de bot **boven** de rollen die hij moet kunnen modereren.

## 2. Lokaal starten
```
pip install -r requirements.txt
cp .env.example .env      # en plak je token erin
python bot.py
```
Vereist Python 3.10 of hoger.

## 3. Eerste setup in je server
- `/instellen log #kanaal` · `/instellen tickets categorie supportrol` · `/instellen welkom #kanaal`
- `/ticketpanel` plaatst de ticketknop
- `/antiraid instellen` en daarna `/antiraid aan`

## 4. Gratis hosting (24/7)
Zet de token altijd als omgevingsvariabele `DISCORD_TOKEN`, nooit in je code of op GitHub.

- **Eigen pc / Raspberry Pi**: echt gratis, geen limieten. Start met `python bot.py` (of met `pm2`/`systemd`).
- **Oracle Cloud "Always Free" VM**: gratis 24/7 server, maar aanmelden vraagt een creditcard ter verificatie
  en je beheert zelf Linux. Draai de bot met `systemd` of `tmux`.
- **Gratis bot-hosts** (bijv. bot-hosting.net, fps.ms): simpel via upload, maar vaak met beperkingen
  (weinig RAM, regelmatig verlengen, wachtrijen). Controleer de actuele voorwaarden.

Let op: `data.json` (waarschuwingen en instellingen) moet bewaard blijven. Op hosts met tijdelijke opslag
raak je die kwijt bij een herstart.

## 5. Dashboard
Het dashboard draait in hetzelfde proces als de bot (poort 8080, of `PORT`). Open `http://localhost:8080`.

**Inloggen** gaat eerst via Discord. Beheerders zijn: een account met een **geverifieerd** e-mailadres uit
`ADMIN_EMAILS` (standaard `matteocleys@gmail.com`), de Discord-gebruikersnaam in `ADMIN_USERNAMES`
(standaard `bloempitbull`) of een ID in `ADMIN_USER_IDS`. Meerdere waarden: scheid met komma's.
Een gebruikersnaam is minder veilig dan een ID (namen kunnen veranderen), vul daarom liever je
Discord-ID in bij `ADMIN_USER_IDS`.

Na het inloggen kies je eerst een server. Je ziet alleen servers waar **zowel de bot als jij** in zit.

Instellen:
1. Developer Portal → je app → **OAuth2** → kopieer **Client ID** en **Client Secret** naar `.env`.
2. Voeg bij **Redirects** toe: `http://localhost:8080/callback` (of `https://jouw-domein/callback`).
3. Staat het dashboard online? Zet `DASHBOARD_URL` op die publieke https-URL, anders werkt inloggen niet.

Wat kan het: overzicht en statistieken (aantal commando's en gebruik), tickets lezen/beantwoorden/sluiten,
commando's per server aan/uit zetten, rollen maken/bewerken/verwijderen, leden zoeken (rol geven,
mute/kick/ban/unban), instellingen en anti-raid aanpassen, aankondigingen versturen.

Veiligheid: laat het dashboard bij voorkeur alleen lokaal draaien, of zet er https voor (bijv. een gratis
Cloudflare Tunnel). Deel `DISCORD_CLIENT_SECRET` nooit.

## 6. GitHub Codespaces (dashboard online proberen)
1. Maak op github.com een **privé**-repository en upload alle bestanden (`.env` en `data.json` niet, die staan in `.gitignore`).
2. Repository → **Settings → Secrets and variables → Codespaces** → voeg toe: `DISCORD_TOKEN`, `DISCORD_CLIENT_ID`,
   `DISCORD_CLIENT_SECRET`, `ADMIN_EMAILS`, `ADMIN_USERNAMES`.
3. Klik op **Code → Codespaces → Create codespace**. De vereisten worden automatisch geinstalleerd.
4. Typ in de terminal: `python bot.py`. Je ziet "Dashboard draait op https://...app.github.dev".
5. Kopieer dat adres, voeg `/callback` toe en zet het in het Developer Portal bij **OAuth2 -> Redirects**.
6. Open het adres in je browser en log in met Discord.

Een Codespace slaapt na een tijd en heeft een maandlimiet aan gratis uren, dus dit is om te testen, niet als vaste hosting.
