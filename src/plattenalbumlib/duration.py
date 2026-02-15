from gettext import ngettext


class Duration():
	def __init__(self, seconds=None):
		if seconds is None:
			self._fallback=True
			self._seconds=0.0
		else:
			self._fallback=False
			self._seconds=float(seconds)

	def __str__(self):
		if self._fallback:
			return "‒‒:‒‒"
		else:
			seconds=int(self._seconds)
			days,seconds=divmod(seconds, 86400) # 86400 seconds make a day
			hours,seconds=divmod(seconds, 3600) # 3600 seconds make an hour
			minutes,seconds=divmod(seconds, 60)
			if days > 0:
				days_string=ngettext("{days} day", "{days} days", days).format(days=days)
				return f"{days_string}, {hours:02d}:{minutes:02d}:{seconds:02d}"
			elif hours > 0:
				return f"{hours}:{minutes:02d}:{seconds:02d}"
			else:
				return f"{minutes:02d}:{seconds:02d}"

	def __float__(self):
		return self._seconds
