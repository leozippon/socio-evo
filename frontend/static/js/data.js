// Read-only access to the published bundle; frontend/README.md is its contract.
//
// Every reference is resolved against the URL of the document that holds it. A reference
// carries the hash of its content, so a document fetched by one is cached for good under its
// full URL; when a changing (`?r=`) file is superseded, the copy under its old reference is
// dropped. Only the manifest and the index are fetched afresh. A 404 for a reference means the
// index has moved on: the run is refreshed and the document asked for again, once.

export const FORMAT = 6;

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
  return { url, runs: index.runs, skipped: index.skipped ?? [], comparisons: index.comparisons ?? [] };
}

/** The comparison of the index whose runs include `run`, if any. */
export const comparisonOf = (index, run) => index?.comparisons.find((found) => found.runs.includes(run)) ?? null;

/** A comparison of groups; a 404 means the index has moved on, so it is read again once. */
export async function readComparison(name) {
  const attempt = async () => {
    const index = await readIndex();
    const entry = index.comparisons.find((found) => found.name === name);
    if (!entry) throw new FetchError(index.url, 404, `— there is no comparison ${name} in this bundle`);
    return { index, entry, doc: await load(resolve(entry.url, index.url)) };
  };
  try {
    return await attempt();
  } catch (error) {
    if (!(error instanceof FetchError) || error.status !== 404 || error.message.includes("no comparison")) throw error;
    return attempt();
  }
}

/** The progress of a run, by the reference its index entry gives. */
export const readProgress = (index, entry) => load(resolve(entry.url, index.url)).then((run) => load(resolve(run.progress, resolve(entry.url, index.url))));

/**
 * One run as currently published. `update(index)` follows the index: when the run's reference
 * has changed it fetches the run document again and reports what changed.
 */
export class RunSource {
  constructor(index, entry) {
    this.key = entry.name;
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
    const entry = index.runs.find((found) => found.name === this.key);
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
    const agents = new Map(before.residents.map((agent) => [agent.name, agent.url]));
    return {
      status: before.status !== after.status,
      timeline: before.timeline !== after.timeline,
      progress: before.progress !== after.progress,
      measures: before.measures !== after.measures,
      evaluation: before.evaluation !== after.evaluation,
      days: after.event_days.filter((day) => days.get(day.day) !== day.url).map((day) => day.day),
      dropped: [...days.keys()].filter((day) => !after.event_days.some((found) => found.day === day)),
      agents: after.residents.filter((agent) => agents.get(agent.name) !== agent.url).map((agent) => agent.name),
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

  timeline() {
    return this.follow(() => resolve(this.doc.timeline, this.url));
  }

  progress() {
    return this.follow(() => resolve(this.doc.progress, this.url));
  }

  measures() {
    return this.follow(() => resolve(this.doc.measures, this.url));
  }

  evaluation() {
    return this.follow(() => resolve(this.doc.evaluation, this.url));
  }

  /** The entries of lived day `day`, which must be one the run has begun. */
  async eventDay(day) {
    const document = await this.follow(() => {
      const entry = this.doc.event_days.find((found) => found.day === day);
      if (!entry) throw new FetchError(this.url, 404, `— the run has no day ${day}`);
      return resolve(entry.url, this.url);
    });
    return document.entries;
  }

  versionsUrl(agent) {
    const entry = this.doc.residents.find((found) => found.name === agent);
    if (!entry) throw new Error(`The run has no resident named ${agent}.`);
    return resolve(entry.url, this.url);
  }

  /** The resident's version history as currently published. */
  versions(agent) {
    return this.follow(() => this.versionsUrl(agent));
  }

  /** The resident's raw trace of lived day `day`, or null if the runtime wrote none that day. */
  trace(agent, day) {
    const entry = this.doc.residents.find((found) => found.name === agent);
    if (!entry) throw new Error(`The run has no resident named ${agent}.`);
    const found = entry.trace_days.find((item) => item.day === day);
    if (!found) return Promise.resolve(null);
    return this.follow(() => resolve(found.url, this.url));
  }

  /** One version of a resident with its diff and files, by commit. */
  version(agent, commit) {
    return this.retry(async () => {
      const history = await this.versions(agent);
      const found = history.versions.find((version) => version.commit === commit);
      if (!found) throw new Error(`${agent} has no version ${commit.slice(0, 8)}.`);
      const day = await load(resolve(found.url, this.versionsUrl(agent)));
      return day.versions.find((version) => version.commit === commit);
    });
  }
}
