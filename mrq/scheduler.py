from .context import log
from .queue import send_task
import datetime


class Scheduler(object):

  def __init__(self, collection):
    self.collection = collection

    self.refresh()

  def refresh(self):
    self.all_tasks = list(self.collection.find())

  def hash_task(self, task):
    return " ".join([str(task.get(x)) for x in ["path", "params", "interval", "dailytime", "queue"]])

  def sync_tasks(self, tasks):
    """ Performs the first sync of a list of tasks, often defined in the config file. """

    tasks_by_hash = {self.hash_task(t): t for t in tasks}

    for task in self.all_tasks:
      if tasks_by_hash.get(task["hash"]):
        del tasks_by_hash[task["hash"]]
      else:
        self.collection.remove({"_id": task["_id"]})
        log.debug("Scheduler: deleted %s" % task["hash"])

    for h, task in tasks_by_hash.iteritems():
      task["hash"] = h
      task["datelastqueued"] = datetime.datetime.fromtimestamp(0)
      if task.get("dailytime"):
        # Because MongoDB can store datetimes but not times, we add today's date to the dailytime.
        # The date part will be discarded in check()
        task["dailytime"] = datetime.datetime.combine(datetime.datetime.utcnow(), task["dailytime"])
        task["interval"] = 3600 * 24
      self.collection.insert(task)
      log.debug("Scheduler: added %s" % task["hash"])

    self.refresh()

  def check(self):

    log.debug("Scheduler checking for out-of-date scheduled tasks (%s scheduled)..." % len(self.all_tasks))
    for task in self.all_tasks:

      now = datetime.datetime.utcnow()
      interval = datetime.timedelta(seconds=task["interval"])

      last_time = now - interval

      if task.get("dailytime"):

        dailytime = task.get("dailytime").time()

        if task.get("datelastqueued") and task.get("datelastqueued").time().isoformat()[0:8] != dailytime.isoformat()[0:8]:
          log.debug("Adjusting the time of scheduled task %s to %s" % (task["_id"], dailytime))

          self.collection.update({"_id": task["_id"]}, {"$set": {
            "datelastqueued": datetime.datetime.combine(task.get("datelastqueued").date() - datetime.timedelta(days=1), dailytime)
          }})
          self.refresh()

      task_data = self.collection.find_and_modify({
        "_id": task["_id"],
        "datelastqueued": {"$lt": last_time}
      }, {"$set": {
        "datelastqueued": datetime.datetime.utcnow()
      }})

      if task_data:
        send_task(task_data["path"], task_data["params"], queue=task.get("queue"))
        log.debug("Scheduler: queued %s" % task_data)

        self.refresh()
