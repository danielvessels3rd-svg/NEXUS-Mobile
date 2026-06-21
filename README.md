# N.E.X.U.S Mobile Relay

This is the small, deliberately limited relay server that lets your
phone talk to your real desktop N.E.X.U.S. It never runs commands
itself -- it only passes messages between your phone and your
desktop, which does the real work through the exact same
`handle_command()` the desktop GUI already uses.

## Deploying to Railway

1. Push this `mobile_relay` folder to a new GitHub repository.
2. In Railway, click "New Project" -> "Deploy from GitHub repo" ->
   select the repository.
3. In Railway's project settings, go to "Variables" and add:
   - `NEXUS_MOBILE_PASSCODE` = a passcode only you know (6+ digits
     or a real word -- this is what both your phone and desktop
     will use to authenticate)
4. Railway will auto-detect the Procfile and deploy.
5. Once deployed, Railway gives you a public URL like
   `https://your-project.up.railway.app` -- that's your relay.

## Connecting your desktop N.E.X.U.S

Set these two environment variables wherever your desktop
N.E.X.U.S runs (see your operator settings file):
- `NEXUS_RELAY_URL` = the Railway URL from step 5 above
- `NEXUS_MOBILE_PASSCODE` = the SAME passcode you set in Railway

Restart N.E.X.U.S. The mobile bridge will start polling
automatically.

## Using it on your phone

Open `https://your-project.up.railway.app/app` in your phone's
browser. Enter the passcode. Optionally tap "Add to Home Screen" in
your browser's menu so it launches like a real app.
