import {getDocument, GlobalWorkerOptions} from '../vendor/pdfjs/pdf.min.mjs';

GlobalWorkerOptions.workerSrc = new URL('../vendor/pdfjs/pdf.worker.min.mjs', import.meta.url).href;

export function mountPdfPreview(target, url) {
  const controls = document.createElement('div');
  controls.className = 'pdf-controls';
  const previous = document.createElement('button');
  previous.textContent = '上一页';
  const next = document.createElement('button');
  next.textContent = '下一页';
  const fit = document.createElement('button');
  fit.textContent = '适应宽度';
  const counter = document.createElement('span');
  counter.textContent = '— / —';
  for (const button of [previous, next, fit]) {
    button.type = 'button';
    button.className = 'outline';
    button.disabled = true;
  }
  controls.append(previous, counter, next, fit);
  const status = document.createElement('p');
  status.className = 'pdf-status';
  status.setAttribute('aria-live', 'polite');
  status.textContent = '正在加载 PDF…';
  const pages = document.createElement('div');
  pages.className = 'pdf-pages';
  target.replaceChildren(controls, status, pages);

  let loadingTask, pdf, renderTask;
  let disposed = false, rendering = false, pageNumber = 1, generation = 0;
  function updateControls() {
    previous.disabled = !pdf || rendering || pageNumber <= 1;
    next.disabled = !pdf || rendering || pageNumber >= pdf.numPages;
    fit.disabled = !pdf || rendering;
    if (pdf) counter.textContent = `第 ${pageNumber} / ${pdf.numPages} 页`;
  }
  function failure(error) {
    status.textContent = `PDF 预览失败：${error.message || error}。可尝试新标签打开或下载。`;
    status.setAttribute('role', 'alert');
    pages.replaceChildren();
  }
  async function showPage(number) {
    const current = ++generation;
    rendering = true;
    pageNumber = number;
    updateControls();
    status.removeAttribute('role');
    status.textContent = `正在渲染第 ${number} 页…`;
    try {
      const page = await pdf.getPage(number);
      if (disposed || current !== generation) return;
      const original = page.getViewport({scale: 1});
      const width = Math.max(1, pages.clientWidth - 24);
      const viewport = page.getViewport({scale: width / original.width});
      const ratio = window.devicePixelRatio || 1;
      const canvas = document.createElement('canvas');
      canvas.width = Math.ceil(viewport.width * ratio);
      canvas.height = Math.ceil(viewport.height * ratio);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = 'auto';
      canvas.setAttribute('aria-label', `PDF 第 ${number} 页`);
      const context = canvas.getContext('2d', {alpha: false});
      if (!context) throw new Error('浏览器无法创建画布');
      pages.replaceChildren(canvas);
      renderTask = page.render({
        canvasContext: context, viewport,
        transform: ratio === 1 ? null : [ratio, 0, 0, ratio, 0, 0],
        background: 'rgb(255,255,255)',
      });
      await renderTask.promise;
      if (disposed || current !== generation) return;
      status.textContent = '';
      pages.scrollTop = 0;
    } catch (error) {
      if (!disposed && current === generation) failure(error);
    } finally {
      if (!disposed && current === generation) {
        rendering = false;
        renderTask = null;
        updateControls();
      }
    }
  }
  previous.onclick = () => showPage(pageNumber - 1);
  next.onclick = () => showPage(pageNumber + 1);
  fit.onclick = () => showPage(pageNumber);
  (async () => {
    try {
      loadingTask = getDocument({url});
      pdf = await loadingTask.promise;
      if (!disposed) await showPage(1);
    } catch (error) {
      if (!disposed) failure(error);
    }
  })();
  return () => {
    disposed = true;
    generation++;
    renderTask?.cancel();
    loadingTask?.destroy().catch(() => {});
    target.replaceChildren();
  };
}
