class EventDispatcher:

    def __init__(self):
        self.listeners={}

    def on(self,event,callback):
        self.listeners.setdefault(event,[]).append(callback)

    def emit(self,event,*args,**kwargs):
        for cb in self.listeners.get(event,[]):
            try:
                cb(*args,**kwargs)
            except Exception as e:
                print(f"[EVENT ERROR] {event}: {e}")

events=EventDispatcher()
