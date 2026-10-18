// Controls are available only when the local viewer exposes its management API.
import { experimentLabel, h } from "./dom.js";

const endpoint = () => new URL("api/experiments", location.href.split("#")[0]);
export async function canManageExperiments() {
  try {
    const response = await fetch(endpoint(), { cache: "no-store" });
    return response.ok && (await response.json()).management === true;
  } catch { return false; }
}

async function changeExperiment(body) {
  const response = await fetch(endpoint(), {
    method: "POST", headers: { "Content-Type": "application/json", "X-Socio-Management": "1" },
    body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Could not update the experiment.");
  return result;
}

export function experimentControls(name, runs, refresh) {
  const label = experimentLabel(name);
  const busy = runs.some(run => !["completed", "interrupted", "failed"].includes(run.status));
  function open(action) {
    const deleting = action === "delete";
    const input = h("input", { type: "text", value: label, maxlength: 120, required: true, "aria-label": "Experiment name" });
    const error = h("p", { class: "management-error", role: "alert" });
    const submit = h("button", { type: "submit", class: deleting ? "btn danger" : "btn" }, deleting ? "Delete experiment" : "Save name");
    const cancel = h("button", { type: "button", class: "ghost", onclick: () => dialog.close() }, "Cancel");
    const form = h("form", { onsubmit: async event => {
      event.preventDefault();
      submit.disabled = true;
      cancel.disabled = true;
      error.textContent = "";
      try {
        await changeExperiment({ action, experiment: name, ...(deleting ? { confirm: name } : { display_name: input.value.trim() }) });
        await refresh();
        dialog.close();
      } catch (failure) { error.textContent = failure.message; }
      finally { submit.disabled = false; cancel.disabled = false; }
    } },
    h("h2", { id: "experiment-dialog-title" }, deleting ? "Delete experiment?" : "Rename experiment"),
    h("p", {}, label),
    h("p", { class: "note" }, `ID: ${name} · ${runs.length} seed${runs.length === 1 ? "" : "s"}`),
    deleting ? h("p", {}, "This removes the experiment and all its seeds from the viewer. Original records move to the server recovery folder; disk space is not freed.") : h("label", {}, "Display name", input),
    deleting ? null : h("p", { class: "note" }, "Existing links and experiment records keep their original IDs."),
    error, h("div", { class: "row management-buttons" }, cancel, submit));
    const dialog = h("dialog", { class: "experiment-dialog", "aria-labelledby": "experiment-dialog-title", onclose: () => dialog.remove() }, form);
    dialog.addEventListener("cancel", event => { if (submit.disabled) event.preventDefault(); });
    document.body.append(dialog);
    dialog.showModal();
    if (deleting) cancel.focus(); else { input.focus(); input.select(); }
  }
  return h("div", { class: "row experiment-controls" },
    h("button", { type: "button", class: "ghost small", onclick: () => open("rename"), "aria-label": `Rename ${label}` }, "Rename"),
    h("button", { type: "button", class: "ghost small danger", disabled: busy, title: busy ? "Stop all running seeds before deleting" : "Remove this experiment from the viewer", onclick: () => open("delete"), "aria-label": `Delete ${label}` }, "Delete"));
}
