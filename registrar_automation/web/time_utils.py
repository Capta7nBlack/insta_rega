# web/time_utils.py

import ntplib
from time import ctime

def get_ntp_time_offset():
    """
    Connects to a network time protocol (NTP) server to get the true time
    and calculates the offset of the local system clock.

    Returns:
        float: The clock offset in seconds. A positive value means the local
               clock is ahead of the true time. A negative value means it's behind.
    """
    ntp_client = ntplib.NTPClient()
    # A reliable public NTP server pool
    ntp_server = 'pool.ntp.org'
    
    try:
        print("⏳ [TimeUtils] Querying NTP server for accurate time...")
        response = ntp_client.request(ntp_server, version=3, port=123)
        # The 'offset' attribute is the difference between the local clock
        # and the true time provided by the server.
        offset = response.offset
        print(f"✅ [TimeUtils] NTP check complete. Local clock offset is {offset:.4f} seconds.")
        return offset
    except Exception as e:
        print(f"⚠️ [TimeUtils] Could not connect to NTP server: {e}")
        print("   -> Defaulting to zero offset. Timing will be based on local clock only.")
        # If we can't get the true time, we assume the local clock is correct.
        return 0.0
