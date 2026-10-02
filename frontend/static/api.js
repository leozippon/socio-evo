// Read-only access to the replay server.

async function get(path) {
  const response = await fetch(`/api/${path}`);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error ?? `${response.status} ${response.statusText}`);
  return body;
}

const enc = encodeURIComponent;

export const listRuns = () => get("runs");
export const runPath = (run) => `runs/${enc(run.experiment)}/${enc(run.directory)}`;
export const getWorld = (run) => get(`${runPath(run)}/world`);
export const getEvents = (run, after) => get(`${runPath(run)}/events?after=${after}`);
export const getEvaluation = (run) => get(`${runPath(run)}/evaluation`);
export const getHistory = (run, agent) => get(`${runPath(run)}/agents/${enc(agent)}/history`);
export const getDiff = (run, agent, commit) => get(`${runPath(run)}/agents/${enc(agent)}/commits/${commit}/diff`);
export const getFiles = (run, agent, commit) => get(`${runPath(run)}/agents/${enc(agent)}/commits/${commit}/files`);
