"""Dev server launcher - sets the Windows event loop policy before uvicorn starts."""

import uvicorn

from demosense.winloop import use_selector_event_loop_on_windows

if __name__ == "__main__":
    use_selector_event_loop_on_windows()
    uvicorn.run("demosense.api.main:app", host="127.0.0.1", port=8000, reload=True)
