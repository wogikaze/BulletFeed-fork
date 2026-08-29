from __future__ import annotations

KNOWNNESS_DELIVERED = "delivered"
KNOWNNESS_DISPLAYED = "displayed"
KNOWNNESS_READ = "read"

WATERMARK_STATES = (KNOWNNESS_DISPLAYED, KNOWNNESS_READ)

# GET /feed may retry an undisplayed claim this many times. The Nth response
# still includes the item; the next GET omits it. Delivered-only rows never
# advance the user-known watermark.
UNDISPLAYED_DELIVERY_RETRY_LIMIT = 3
