// Replays a run through the viewer's own modules and prints the final state as JSON.
// Usage: node replay_final.mjs <server base url> <experiment/seed>
import { Replay } from "../../frontend/static/replay.js";

const [base, run] = process.argv.slice(2);
const get = async (path) => (await fetch(`${base}/api/runs/${run}/${path}`)).json();
const world = await get("world");
const replay = new Replay(world);
replay.append((await get("events")).events);
const state = replay.seek(replay.end);
// Scrubbing back and forth must land on the same state as playing straight through.
const middle = JSON.stringify(replay.seek((replay.start + replay.end) / 2));
const again = JSON.stringify(replay.seek((replay.start + replay.end) / 2));
const back = JSON.stringify(new Replay({ ...world }).events.length);
console.log(
  JSON.stringify({
    balances: state.balances,
    locations: state.locations,
    esteem: replay.seek(replay.end).esteem,
    stable: middle === again && back === "0",
  }),
);
