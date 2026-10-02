// Read-only access to the published data bundle (frontend/README.md is its contract).
// An interim adapter: it answers in the shapes the viewer's panels were written for.

const FORMAT = 1;

async function fetchJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}`);
  return response.json();
}

// A reference carries the hash of its content, so a document fetched by one never changes.
const documents = new Map();
function load(url) {
  if (!documents.has(url))
    documents.set(
      url,
      fetchJSON(url).catch((error) => {
        documents.delete(url);
        throw error;
      }),
    );
  return documents.get(url);
}

const resolve = (ref, base) => new URL(ref, base).href;

async function index() {
  const url = new URL("data/index.json", location.href).href;
  const found = await fetchJSON(url);
  if (found.format !== FORMAT) throw new Error(`The data bundle has format ${found.format}; this viewer reads format ${FORMAT}.`);
  return { url, runs: found.runs };
}

/** The run's document as currently published, and its URL. */
async function runDocument(run) {
  const { url, runs } = await index();
  const entry = runs.find((r) => r.experiment === run.experiment && r.run === run.directory);
  if (!entry) throw new Error(`${run.experiment}/${run.directory} is no longer published.`);
  const at = resolve(entry.url, url);
  return { url: at, doc: await load(at) };
}

export async function listRuns() {
  const { runs } = await index();
  return runs.map((r) => ({ ...r, directory: r.run, days_done: r.settled_day }));
}

export async function getWorld(run) {
  const { url, doc } = await runDocument(run);
  return load(resolve(doc.world, url));
}

export async function getEvents(run, after) {
  const { url, doc } = await runDocument(run);
  const files = await Promise.all(doc.event_days.filter((d) => d.last_seq > after).map((d) => load(resolve(d.url, url))));
  const events = files.flatMap((file) => file.events).filter((e) => e.seq > after);
  return { status: doc.status, events, last: events.length ? events.at(-1).seq : after };
}

async function versionsOf(run, agent) {
  const { url, doc } = await runDocument(run);
  const at = resolve(doc.agents.find((a) => a.agent === agent).url, url);
  return { url: at, doc: await load(at) };
}

export const getHistory = async (run, agent) => (await versionsOf(run, agent)).doc.versions;

async function versionAt(run, agent, commit) {
  const { url, doc } = await versionsOf(run, agent);
  const day = await load(resolve(doc.versions.find((v) => v.commit === commit).url, url));
  return { url, doc, version: day.versions.find((v) => v.commit === commit) };
}

export async function getDiff(run, agent, commit) {
  return { commit, diff: (await versionAt(run, agent, commit)).version.diff };
}

export async function getFiles(run, agent, commit) {
  const { url, doc, version } = await versionAt(run, agent, commit);
  const { policy, skills, insights, diary } = version.state;
  const latest = diary.at(-1);
  let entry = null;
  if (latest !== undefined) {
    const file = await load(resolve(doc.diary.find((d) => d.day === latest).url, url));
    entry = { name: `day-${String(latest).padStart(4, "0")}`, text: file.diary.find((d) => d.day === latest).text };
  }
  return { commit, policy: policy ?? "", skills, insights, diary: entry };
}
