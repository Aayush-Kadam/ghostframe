from ghostframe import CapturePolicy, Recorder, trace_tool

recorder = Recorder(
    storage=".ghostframe/example.db", project="synthetic-example", policy=CapturePolicy(enabled=True)
)


@trace_tool(recorder=recorder)
def read_ticket(ticket_id):
    return {"ticket_id": ticket_id, "action": "archive"}


with recorder.run("example execution") as run_id:
    print(read_ticket("ticket-001"))
print("Playback-only run:", run_id)
