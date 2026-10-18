from datetime import timedelta

DOMAIN = "babble"

CONF_URL = "url"
CONF_SUPABASE_URL = "supabase_url"
CONF_ANON_KEY = "anon_key"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_ACCESS_TOKEN = "access_token"
CONF_EXPIRES_AT = "expires_at"

UPDATE_INTERVAL = timedelta(seconds=30)
TICK_INTERVAL = timedelta(minutes=1)
LINK_POLL_SECONDS = 3
LINK_TIMEOUT_SECONDS = 300
DEVICE_HEADER = "x-babble-device"
DEVICE_NAME = "Home Assistant"
