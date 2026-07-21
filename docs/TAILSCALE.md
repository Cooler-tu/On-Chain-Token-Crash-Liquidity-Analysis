# Publishing the Dashboard with Tailscale

The dashboard is a static local report. Run it first:

```bash
python3 -m src.cli serve-dashboard --output-dir output --port 8080
```

Keep that terminal running while sharing the site.

## Share within your Tailscale network

Install Tailscale and log in with the account that owns the tailnet, then run:

```bash
tailscale serve 8080
tailscale serve status
```

The status command prints the private `https://<machine>.<tailnet>.ts.net` URL. Only devices and users allowed by your tailnet policy can open it.

## Share publicly

Funnel exposes the local report to the public Internet. Confirm that the output does not contain information you do not intend to publish, then run:

```bash
tailscale funnel --https=443 8080
tailscale funnel status
```

The status output gives the public HTTPS URL. Stop publishing when it is no longer needed:

```bash
tailscale funnel --https=443 off
```

Funnel requires a logged-in Tailscale node and may ask the tailnet administrator to approve HTTPS/Funnel settings. On macOS, serving a port (as above) is preferable to giving Funnel a local directory path.
