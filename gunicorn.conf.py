# gunicorn.conf.py
# Fixes file upload body reading on Render (proxy strips Transfer-Encoding: chunked)

worker_class = "gevent"
workers = 1
worker_connections = 100
timeout = 120
keepalive = 5

# Allow gunicorn to trust Render's proxy headers
forwarded_allow_ips = "*"
