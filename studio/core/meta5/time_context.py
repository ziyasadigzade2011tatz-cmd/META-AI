"""System-clock context shared by conversation and agent requests."""
from datetime import datetime,timedelta

def now_context():
    current=datetime.now().astimezone()
    return {'now':current.isoformat(timespec='seconds'),'timezone':str(current.tzinfo),
            'weekday':current.strftime('%A'),'today':current.date().isoformat(),
            'tomorrow':(current+timedelta(days=1)).date().isoformat(),
            'yesterday':(current-timedelta(days=1)).date().isoformat(),
            'part_of_day':'morning' if 5<=current.hour<12 else 'afternoon' if 12<=current.hour<18 else 'evening' if 18<=current.hour<23 else 'night'}
