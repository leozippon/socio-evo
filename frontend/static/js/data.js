// Read-only access to the published bundle; frontend/README.md is its contract.
//
// Every reference is resolved against the URL of the document that holds it. A reference
// carries the hash of its content, so a document fetched by one is cached for good under its
// full URL; when a changing (`?r=`) file is superseded, the copy under its old reference is
// dropped. Only the manifest and the index are fetched afresh. A 404 for a reference means the
// index has moved on: the run is refreshed and the document asked for again, once.

export const FORMAT = 1;

export class FetchError extends Error {
  constructor(url, status, detail) {
    const where = decodeURIComponent(new URL(url).pathname.replace(/^.*?\/data\//, "data/"));
    super(status ? `${where}: HTTP ${status}${detail ? ` ${detail}` : ""}` : `${where}: ${detail}`);
    this.url = url;
    this.status = status;
  }
}

export class FormatError extends Error {}

async function getJSON(url, fresh = false) {
  let response;
  try {
    response = await fetch(url, fresh ? { cache: "no-store" } : {});
  } catch (error) {
    throw new FetchError(url, 0, `could not be fetched (${error.message})`);
  }
  if (!response.ok) throw new FetchError(url, response.status, response.statusText);
  try {
    return await response.json();
  } catch (error) {
    throw new FetchError(url, response.status, `is not valid JSON (${error.message})`);
  }
}

const documents = new Map(); // absolute URL -> promise of its document
const current = new Map(); // URL without query -> the absolute URL last asked for

/** The document at an absolute URL that carries a content hash, fetched at most once. */
export function load(url) {
  if (!documents.has(url)) {
    const path = url.split("?")[0];
    const before = current.get(path);
    if (before && before !== url && before.includes("?r=")) documents.delete(before);
    current.set(path, url);
    const promise = getJSON(url).catch((error) => {
      documents.delete(url);
      throw error;
    });
    documents.set(url, promise);
  }
  return documents.get(url);
}

export const resolve = (ref, base) => new URL(ref, base).href;

const here = (path) => new URL(path, location.href).href;

/** The bundle's manifest; refuses a bundle of another format. */
export async function readManifest() {
  const manifest = await getJSON(here("data/manifest.json"), true);
  if (manifest.format !== FORMAT)
    throw new FormatError(
      `This data bundle has format ${manifest.format}, but this viewer reads format ${FORMAT}. Publish the runs again with the viewer that ships with the same version of the publisher.`,
    );
  return manifest;
}

/** The index of every run, fetched afresh. */
export async function readIndex() {
  const url = here("data/index.json");
  const index = await getJSON(url, true);
  if (index.format !== FORMAT) throw new FormatError(`The run index has format ${index.format}, but this viewer reads format ${FORMAT}.`);
  return { url, runs: index.runs };
}

export const runKey = (entry) => `${entry.experiment}/${entry.run}`;

/**
 * One run as currently published. `update(index)` follows the index: when the run's reference
 * has changed it fetches the run document again and reports what changed.
 */
export class RunSource {
  constructor(index, entry) {
    this.key = runKey(entry);
    this.indexUrl = index.url;
    this.entry = entry;
    this.url = null;
    this.doc = null;
    this.refreshing = null;
    this.onRefresh = null; // called with the index whenever this source refreshes it
  }

  async open() {
    this.url = resolve(this.entry.url, this.indexUrl);
    this.doc = await load(this.url);
    return this;
  }

  /** Follow a newer index; returns what changed, or null if nothing did. */
  async update(index) {
    const entry = index.runs.find((found) => runKey(found) === this.key);
    if (!entry) throw new FetchError(this.url, 404, "— the run is no longer published");
    this.indexUrl = index.url;
    if (resolve(entry.url, index.url) === this.url) {
      this.entry = entry;
      return null;
    }
    const before = this.doc;
    this.entry = entry;
    await this.open();
    const after = this.doc;
    const days = new Map(before.event_days.map((day) => [day.day, day.url]));
    const agents = new Map(before.agents.map((agent) => [agent.agent, agent.url]));
    return {
      status: before.status !== after.status,
      measures: before.measures !== after.measures,
      evaluation: before.evaluation !== after.evaluation,
      days: after.event_days.filter((day) => days.get(day.day) !== day.url).map((day) => day.day),
      dropped: [...days.keys()].filter((day) => !after.event_days.some((found) => found.day === day)),
      agents: after.agents.filter((agent) => agents.get(agent.agent) !== agent.url).map((agent) => agent.agent),
    };
  }

  /** Fetch the index again and follow it; shared by everyone who asks at the same time. */
  refresh() {
    this.refreshing ??= readIndex()
      .then(async (index) => {
        await this.update(index);
        this.onRefresh?.(index);
      })
      .finally(() => (this.refreshing = null));
    return this.refreshing;
  }

  /** Run `attempt`, and once more after a refresh if a reference it followed had gone. */
  async retry(attempt) {
    try {
      return await attempt();
    } catch (error) {
      if (!(error instanceof FetchError) || error.status !== 404) throw error;
      await this.refresh();
      return attempt();
    }
  }

  /** Load the document a reference names, refreshing the run once if it has gone. */
  follow(locate) {
    return this.retry(() => load(locate()));
  }

  world() {
    return this.follow(() => resolve(this.doc.world, this.url));
  }

  measures() {
    return this.follow(() => resolve(this.doc.measures, this.url));
  }

  evaluation() {
    return this.follow(() => resolve(this.doc.evaluation, this.url));
  }

  /** The events of `day`, which must be one the run has begun. */
  async eventDay(day) {
    const document = await this.follow(() => {
      const entry = this.doc.event_days.find((found) => found.day === day);
      if (!entry) throw new FetchError(this.url, 404, `— the run has no day ${day}`);
      return resolve(entry.url, this.url);
    });
    return document.events;
  }

  versionsUrl(agent) {
    const entry = this.doc.agents.find((found) => found.agent === agent);
    if (!entry) throw new Error(`The run has no agent named ${agent}.`);
    return resolve(entry.url, this.url);
  }

  /** The agent's version history as currently published. */
  versions(agent) {
    return this.follow(() => this.versionsUrl(agent));
  }

  /** One version of an agent with its diff and readable state, by commit. */
  version(agent, commit) {
    return this.retry(async () => {
      const history = await this.versions(agent);
      const found = history.versions.find((version) => version.commit === commit);
      if (!found) throw new Error(`${agent} has no version ${commit.slice(0, 8)}.`);
      const day = await load(resolve(found.url, this.versionsUrl(agent)));
      return day.versions.find((version) => version.commit === commit);
    });
  }

  /** The text of an agent's diary entry about `day`, as its latest version holds it. */
  diary(agent, day) {
    return this.retry(async () => {
      const history = await this.versions(agent);
      const found = history.diary.find((entry) => entry.day === day);
      if (!found) return null;
      const document = await load(resolve(found.url, this.versionsUrl(agent)));
      return document.diary.find((entry) => entry.day === day)?.text ?? null;
    });
  }

  /** An evaluation result, by a reference held in evaluation.json. */
  result(ref) {
    return this.follow(() => resolve(ref, resolve(this.doc.evaluation, this.url)));
  }
}
