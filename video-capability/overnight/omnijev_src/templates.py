"""Action-space templates: the thing a caller has to supply so a decision model can act.

A System One model cannot invent an action space, so every embodied / GUI / game domain ships
one here: the options it may choose between, the statements worth asking, and the levels of its
score questions. `questions(domain, **ctx)` returns a ready `questions` dict for `system_one`,
so an agent loop is:

    st = {"images": [frame]}
    ans = mso.system_one(st, templates.questions("libero", instruction=task))
    act = ans["action"]["choice"]; p = ans["action"]["probabilities"]

Region options (where to click / which square / which cell) are filled in by the caller from
whatever proposes regions at runtime: the DOM for a browser, an element detector for a
screenshot, or `grid(rows, cols)` below when nothing proposes anything - the model then points
by choosing a cell, and a second call refines inside that cell (see docs in build_pointing.py).
"""

# ----------------------------------------------------------------- spaces ---
DIRECTIONS_3D = ["forward", "backward", "left", "right", "up", "down", "stay still"]
GRIPPER = ["open the gripper", "close the gripper", "keep the gripper as it is"]
BROWSER_OPS = ["click", "type text", "select from a dropdown", "scroll down", "scroll up", "go back", "the task is done"]
PHONE_OPS = ["click", "input_text", "long_press", "navigate_back", "navigate_home", "open_app", "scroll", "wait"]
GAMEPAD = ["left", "right", "up", "down", "jump", "shoot", "do nothing"]
DRONE = ["fly forward", "fly backward", "yaw left", "yaw right", "ascend", "descend", "hover"]
NAV_STEPS = ["go forward", "turn left", "turn right", "turn around", "stop: the goal is reached"]
RISK = ["harmless", "needs care", "irreversible"]
PROGRESS = ["just started", "less than halfway", "more than halfway", "almost done"]
FILES = ["0", "1", "2", "3", "4 or more"]

SQUARES = [f + r for r in "87654321" for f in "abcdefgh"]


def grid(rows=8, cols=12, key="cell"):
    """A fixed grid of region options covering the whole image, in 0-1000 coordinates.
    Nothing has to propose regions: the model points by picking a cell."""
    out = []
    for r in range(rows):
        for c in range(cols):
            out.append({"key": "%s r%dc%d" % (key, r, c),
                        "region": {"box": [round(c * 1000 / cols), round(r * 1000 / rows),
                                           round((c + 1) * 1000 / cols), round((r + 1) * 1000 / rows)]}})
    return out


def zoom_grid(box, rows=8, cols=12, key="fine"):
    """The same grid inside a previously chosen box (second, refining call)."""
    x0, y0, x1, y1 = box
    w, h = (x1 - x0) / cols, (y1 - y0) / rows
    return [{"key": "%s r%dc%d" % (key, r, c),
             "region": {"box": [round(x0 + c * w), round(y0 + r * h), round(x0 + (c + 1) * w), round(y0 + (r + 1) * h)]}}
            for r in range(rows) for c in range(cols)]


def _choice(instr, options, abstain=True):
    opts = [{"key": o, "text": o} if isinstance(o, str) else o for o in options]
    if abstain:
        opts = opts + [{"abstain": True}]
    return {"type": "choice", "instructions": instr, "options": opts}


def _score(instr, levels):
    return {"type": "score", "instructions": instr, "levels": list(levels)}


def _noul(instr, region=None):
    q = {"type": "noul", "instructions": instr}
    if region:
        q["region"] = {"box": region}
    return q


# -------------------------------------------------------------- templates ---
def questions(domain, **ctx):
    """domain -> {qid: question}. ctx supplies the goal/instruction and any region options."""
    d = domain.lower()
    if d in ("libero", "robot", "manipulation"):
        task = ctx.get("instruction", "the task")
        qs = {
            "action": _choice("Robot camera view. Instruction: %s. During the next second, in which direction should the gripper mainly move?" % task, DIRECTIONS_3D, abstain=False),
            "gripper": _choice("Robot camera view. Instruction: %s. What should happen to the gripper next?" % task, GRIPPER, abstain=False),
            "holding": _noul("Robot camera view. The gripper is currently closed on an object."),
            "done": _noul("Robot camera view. The instruction '%s' has been completed." % task),
            "progress": _score("Robot camera view. Instruction: %s. How far along is the task?" % task, PROGRESS),
        }
        if ctx.get("subtasks"):
            qs["phase"] = _choice("Robot camera view. Instruction: %s. Which part is the robot working on right now?" % task,
                                  list(ctx["subtasks"]) + ["both parts are already done"])
        if ctx.get("instructions"):
            qs["which"] = _choice("Robot camera view. Which instruction is this robot executing?", list(ctx["instructions"]))
        return qs
    if d in ("browser", "web"):
        goal = ctx.get("goal", "the task")
        hist = ctx.get("history", "")
        head = "Task: %s.%s" % (goal, (" Done so far: " + hist) if hist else " Nothing has been done yet.")
        qs = {
            "op": _choice(head + " What kind of operation comes next on this page?", BROWSER_OPS),
            "goal_met": _noul(head + " The task is already complete on this page."),
            "stuck": _noul(head + " This page cannot make progress toward the task."),
            "risk": _score(head + " How irreversible is the next action?", RISK),
        }
        if ctx.get("elements"):
            qs["target"] = _choice(head + " Which highlighted element should be interacted with next?", ctx["elements"])
        else:
            qs["target"] = _choice(head + " Which region of the screen should be interacted with next?", grid(*ctx.get("grid", (8, 12))))
        return qs
    if d in ("phone", "android", "gui"):
        goal = ctx.get("goal", "the task")
        step = ctx.get("step", "")
        head = "Goal: %s.%s" % (goal, (" Next step: " + step) if step else "")
        return {
            "action": _choice(head + " Which action should be performed on this screen?", PHONE_OPS),
            "target": _choice(head + " Which region should be tapped?", ctx.get("elements") or grid(*ctx.get("grid", (8, 12)))),
            "risk": _score(head + " How irreversible is the next action on this screen?", RISK),
            "error": _noul("This screen shows an error dialog."),
        }
    if d == "chess":
        side = ctx.get("turn", "the side to move")
        return {
            "check": _noul("Chess position. The side to move is in check."),
            "mate": _noul("Chess position. This position is checkmate."),
            "king": _choice("Chess position. Which marked square holds the %s king?" % side, ctx.get("squares") or grid(8, 8, key="square")),
            "move_to": _choice("Chess position. Which square should the best move go to?", ctx.get("squares") or grid(8, 8, key="square")),
            "material": _score("Chess position. How does the material stand for %s?" % side,
                               ["much worse", "slightly worse", "equal", "slightly better", "much better"]),
            "pieces": _score("Chess position. How many pieces (not pawns, not the king) does %s have?" % side, FILES),
        }
    if d in ("game", "platformer", "atari"):
        goal = ctx.get("goal", "score points and stay alive")
        return {
            "action": _choice("Game screen. Goal: %s. Which button should be pressed next?" % goal, ctx.get("buttons") or GAMEPAD, abstain=False),
            "danger": _noul("Game screen. The player is in immediate danger."),
            "target": _choice("Game screen. Which region holds the thing the player should go to next?", ctx.get("elements") or grid(*ctx.get("grid", (6, 8)))),
            "progress": _score("Game screen. How well is the player doing?", ["losing badly", "behind", "even", "ahead"]),
        }
    if d in ("drone", "uav", "aerial"):
        goal = ctx.get("goal", "reach the landing pad")
        return {
            "action": _choice("Drone camera view. Goal: %s. What should the drone do next?" % goal, DRONE, abstain=False),
            "obstacle": _noul("Drone camera view. There is an obstacle straight ahead within a few metres."),
            "target": _choice("Drone camera view. Which region shows the target?", ctx.get("elements") or grid(*ctx.get("grid", (6, 8)))),
            "altitude": _score("Drone camera view. How high is the drone above the ground?", ["at ground level", "low", "medium", "high"]),
        }
    if d in ("navigation", "vln", "indoor"):
        goal = ctx.get("goal", "the goal")
        return {
            "action": _choice("First-person view. Goal: %s. What is the next move?" % goal, NAV_STEPS, abstain=False),
            "arrived": _noul("First-person view. The goal '%s' is visible right here." % goal),
            "target": _choice("First-person view. Which region should be moved toward?", ctx.get("elements") or grid(*ctx.get("grid", (6, 8)))),
            "remaining": _score("First-person view. How many more moves are needed to reach the goal?", FILES),
        }
    if d in ("wiki", "navigate_links"):
        goal, cur, step = ctx.get("goal", "?"), ctx.get("current", "?"), ctx.get("step", 0)
        head = "You are navigating by clicking links. Goal: reach \"%s\". Current page: \"%s\". Clicks so far: %d." % (goal, cur, step)
        return {
            "link": _choice(head + " Which highlighted link should be clicked next to get closer to the goal?", ctx.get("elements") or grid(8, 12, key="link")),
            "arrived": _noul(head + " The current page is the goal page."),
            "reach3": _noul(head + " The goal can be reached from this page within 3 more clicks."),
            "remaining": _score(head + " How many more clicks are needed to reach the goal?", FILES),
        }
    raise KeyError("no template for domain %r; known: libero, browser, phone, chess, game, drone, navigation, wiki" % domain)


DOMAINS = ["libero", "browser", "phone", "chess", "game", "drone", "navigation", "wiki"]


def describe():
    out = {}
    for d in DOMAINS:
        ctx = {"instruction": "...", "goal": "...", "current": "...", "subtasks": ["part one", "part two"], "instructions": ["a", "b"]}
        qs = questions(d, **ctx)
        out[d] = {qid: {"type": q["type"],
                        "n_options": len(q.get("options", q.get("levels", [])))} for qid, q in qs.items()}
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(describe(), indent=1))
