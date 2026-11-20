# Deploy GlideCRM on one virtual machine

This is the production path for a few users. One Ubuntu server runs Docker.
The same machine runs the CRM, MySQL, the reminder loop, and Caddy.
MySQL accepts connections only from the other containers.

Local laptop setup stays in [DEVELOPMENT.md](DEVELOPMENT.md). Use this file
on the server.

## Address: IP now, a name later

Open the CRM at `https://` plus the server's public IP address, for example
`https://203.0.113.10`. Use the IP your provider shows for the new machine.
`203.0.113.10` in the example files is a placeholder, not a real server.

An IP address does not have a subdomain. `crm.203.0.113.10` is not a name
you can register. A subdomain such as `crm.example.com` exists only after
you own `example.com` and create a DNS record that points at this server.
When you have that name, put it in `SITE_ADDRESS` and in the Django host
settings below, then restart the stack. The same containers stay in place.

Let's Encrypt can issue a certificate for a public IP. Those certificates
last about six days and renew on their own. The project Caddyfile asks for
that short-lived profile. Confirm these two pages still describe that
behavior before the first boot, because the Caddy option is marked
experimental:

- https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability.html
- https://caddyserver.com/docs/caddyfile/directives/tls

The server's ports 80 and 443 must be reachable from the internet so the
certificate can be issued and renewed. A home router or a firewall that
blocks port 80 will leave the browser without a trusted certificate.

## Cost

Check the provider's price page on the day you order. The figures below are
ranges, not a quote.

| Item | What to expect |
|---|---|
| Virtual machine, 2 CPU, 4 GB memory, about 40 GB disk | About $6–18 per month. The low end is a budget host. The high end is a larger brand's small plan. I could not refresh a live price for a named provider in the last pass. |
| Disk and traffic for a few users | Included with the plans above at this size. |
| Domain, only if you buy one later | About $10–15 per year. |
| Certificate | $0 from Let's Encrypt. |
| Encrypted backup copy | $0 while the backups stay under 10 GB on Backblaze B2 or Cloudflare R2. Both publish a 10 GB free allowance. Confirm it when you open the account. Above that, this CRM is still well under $1 per month. |

A practical monthly total is about $7–20 before a domain. Set a billing
alert at $25 on the day you open the account. The button lives in the
provider's billing or notifications page. The label differs by company.
The alert should email you when the month's charges reach $25.

Choose 4 GB of memory. MySQL plus the CRM is tight on 1 GB.

## Before you create the server

1. Turn on multi-factor authentication on the cloud account.
2. On the create-server screen, turn on disk encryption if it is offered.
   If the screen does not mention encryption, read the provider's storage
   page. Many hosts encrypt disks by default and do not show a checkbox.
3. Choose Ubuntu LTS. The commands below match Ubuntu. For another image,
   follow that image's own documentation for SSH and the firewall.
4. Add your SSH public key. Do not upload a password for the server login.

## First login and host lockdown

Replace `203.0.113.10` with the public IP, and `YOUR.HOME.IP` with the
address your internet connection uses (search "what is my ip" from that
network).

```bash
ssh ubuntu@203.0.113.10
```

Then, on the server:

```bash
sudo apt-get update
sudo apt-get install -y unattended-upgrades fail2ban
sudo dpkg-reconfigure -plow unattended-upgrades
```

Edit `/etc/ssh/sshd_config` so these lines are set, then restart SSH:

```
PermitRootLogin no
PasswordAuthentication no
```

```bash
sudo systemctl reload ssh
```

If `reload ssh` reports that the service is named `sshd`, use that name
instead. Confirm the Ubuntu SSH service name if the command fails.

Allow only web traffic from the world, and SSH only from your IP:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow from YOUR.HOME.IP to any port 22 proto tcp
sudo ufw enable
```

Also set the same rules in the provider's firewall if it has one. The host
firewall and the provider firewall are two separate doors.

Fail2ban's stock SSH jail is enough for this server. It watches SSH
failures and temporarily blocks the source. Confirm the jail is active
with `sudo fail2ban-client status sshd`.

## Put the application on the server

```bash
sudo apt-get install -y git docker.io docker-compose-v2
sudo usermod -aG docker "$USER"
```

Log out and back in so the docker group applies. Then:

```bash
git clone https://github.com/devsatishvarma/fluxcrm.git
cd fluxcrm
cp .env.production.example .env
```

Edit `.env` and replace every `replace-with` value and the example IP.

Create the secret on the server. Do not invent a short one, and do not
commit `.env`.

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

Paste that into `DJANGO_SECRET_KEY`. Generate two more different values
for `MYSQL_PASSWORD` and `MYSQL_ROOT_PASSWORD`.

Set:

- `SITE_ADDRESS` to the public IP only. No `https://` and no port.
- `DJANGO_ALLOWED_HOSTS` to that same IP.
- `DJANGO_CSRF_TRUSTED_ORIGINS` to `https://` plus that IP.
- `DJANGO_PASSWORD_RESET_ENABLED=false` until you choose an email provider.
- `DJANGO_LOG_LEVEL=INFO`. `DEBUG` logging can write database values,
  including email addresses, into the log.

Start the stack:

```bash
docker compose -f compose.production.yaml up -d --build
```

Four containers start: `database`, `web`, `scheduler`, and `caddy`.
The scheduler is the in-app reminder loop. It is not a separate product
and it does not add Redis. MySQL has no host port. Only Caddy listens on
80 and 443.

Watch the certificate:

```bash
docker compose -f compose.production.yaml logs -f caddy
```

Wait until the log says a certificate was obtained. Then open
`https://YOUR.IP` in a browser. The first page is the setup form. Create
the administrator there and store the password in a password manager.
There is no password-reset email until you pick a mail provider.

If the certificate is not issued, leave HSTS as it is only after a
successful HTTPS load. The example file sets HSTS to one day. A browser
receives that header only on a successful HTTPS response.

Static files are served by the CRM process (WhiteNoise). Uploaded files
and import CSVs stay in the `uploads` Docker volume, which survives a
container rebuild.

## Two-factor authentication

Not enabled in this version. The library to evaluate is
`django-two-factor-auth` (it uses `django-otp`). On PyPI, the current
release's Django classifiers stop at Django 5.2, and this CRM runs Django 6.
Check the project's current install page and Django support list before
adding it. Do not guess the settings.

Until that is confirmed, the server login, the cloud account, and a long
CRM password are the controls that are actually on.

## Who can see what, and what is recorded

Roles already limit each user to the records they are allowed to read and
change. The audit log records creates, updates, deletes, exports, and
import authorize, commit, and rollback. Opening a record is not written
to the audit log. Audit rows for accounts and contacts include the contact
details that changed. Those rows stay in the database and in backups.

## Backups

The backup is a database dump plus the uploads, packed together and
encrypted with a passphrase. Pick a long passphrase and store it somewhere
other than the server. Without it, the file cannot be restored.

Put the passphrase in a root-only file:

```bash
sudo install -m 600 /dev/null /etc/fluxcrm-backup.env
sudo editor /etc/fluxcrm-backup.env
```

The file should contain:

```
BACKUP_PASSPHRASE='a long passphrase that is not in git'
BACKUP_RCLONE_DEST=''
```

Leave `BACKUP_RCLONE_DEST` empty until you choose storage. Backblaze B2
and Cloudflare R2 both speak the API rclone uses, and both have a free
tier large enough for this CRM. Creating either account is a separate
decision. After you create it, install rclone, run `rclone config`, and
set `BACKUP_RCLONE_DEST` to the remote path rclone prints, such as
`b2:glidecrm-backups`. Confirm the remote name in rclone's own docs:
https://rclone.org/docs/

Run one backup by hand:

```bash
cd ~/fluxcrm
set -a
source /etc/fluxcrm-backup.env
set +a
./scripts/backup_daily.sh
```

Schedule it every day at 03:15. `crontab -e` as root:

```
15 3 * * * set -a; . /etc/fluxcrm-backup.env; set +a; cd /home/ubuntu/fluxcrm && ./scripts/backup_daily.sh >> /var/log/fluxcrm-backup.log 2>&1
```

Change `/home/ubuntu/fluxcrm` if you cloned the repo somewhere else.
Local copies older than 14 days are deleted. When the remote is set,
remote copies older than 14 days are deleted too. Confirm rclone's
`delete --min-age` flag in its docs before the first scheduled run.

A backup that exists only on the same disk as the database is not enough.
Set `BACKUP_RCLONE_DEST` before you treat the CRM as the only copy of
customer data.

## Test a restore

Do this once before you rely on the backup, against an empty database
name, not the live one.

```bash
cd ~/fluxcrm
set -a
source /etc/fluxcrm-backup.env
set +a
RESTORE_CONFIRM=glidecrm RESTORE_DATABASE=glidecrm_restore_drill RESTORE_UPLOADS=0 \
  ./scripts/restore_database.sh backups/glidecrm-TIMESTAMP.tar.gz.enc
```

Use the real file name from the `backups/` directory. Then:

```bash
docker compose -f compose.production.yaml exec database \
  sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N -e "SHOW TABLES FROM glidecrm_restore_drill"'
```

You should see `django_migrations` in the list. Then drop the drill
database:

```bash
docker compose -f compose.production.yaml exec database \
  sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -e "DROP DATABASE glidecrm_restore_drill"'
```

Write down the backup file name, the time, and that the table list
appeared. A later restore of the live database uses the same script
without `RESTORE_DATABASE`. That replaces live data. Take a fresh backup
first.

## Day to day

Logs from the CRM go to the container's standard output. They include the
request path, status, and user id. They are not a place for customer
names or message bodies. Read them with:

```bash
docker compose -f compose.production.yaml logs web
```

`https://YOUR.IP/health/` answers if the process is up.
`https://YOUR.IP/ready/` also checks MySQL. Neither page shows customer data.

Stop the stack with:

```bash
docker compose -f compose.production.yaml down
```

That keeps the database and upload volumes. `down -v` deletes them.

## When you buy a domain

1. Create an A record from the name you want to the server IP.
2. In `.env`, set `SITE_ADDRESS` to that name, `DJANGO_ALLOWED_HOSTS` to
   that name, and `DJANGO_CSRF_TRUSTED_ORIGINS` to `https://` plus that name.
3. `docker compose -f compose.production.yaml up -d`
4. Open `https://that-name` and confirm the certificate.

Keep the Caddyfile's short-lived profile unless the Let's Encrypt page
says domain names should use a different profile.
