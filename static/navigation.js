/* Ordinary hrefs own navigation. On HTTP(S), eligible links within the current
   module may fetch and replace the contents tree and main region instead.
   The header, footer, module state and scripts persist; exercise behaviour is then
   reinitialised. Home, other modules and file previews use full page loads. */
(() => {
  "use strict";

  if (!['http:', 'https:'].includes(window.location.protocol)) {
    return;
  }

  const navigation = document.querySelector('[data-site-navigation]');
  const main = document.querySelector('[data-page-content]');
  const siteData = document.getElementById('site-data');
  if (!navigation || !main || !siteData) {
    return;
  }

  const moduleId = JSON.parse(siteData.textContent).module;
  const mobile = window.matchMedia('(max-width: 48rem)');
  const courseNavigator = navigation.querySelector('[data-course-navigator]');
  courseNavigator.open = !mobile.matches;
  mobile.addEventListener('change', () => { navigatorForPage().open = !mobile.matches; });

  function navigatorForPage() {
    return document.querySelector('[data-course-navigator]');
  }

  if (!moduleId) return;
  const moduleRoot = new URL(document.querySelector(`[data-module-overview="${moduleId}"]`).href).pathname.replace(/index\.html$/, '');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let activeRequest = null;
  let navigationNumber = 0;
  let renderedUrl = new URL(window.location.href);

  // Persistent site chrome keeps its original link targets as the URL changes.
  document.querySelectorAll('.site-header a[href], .site-footer a[href]').forEach((link) => {
    link.href = new URL(link.getAttribute('href'), window.location.href).href;
  });
  document.documentElement.classList.add('enhanced-navigation');
  if ('scrollRestoration' in history) {
    history.scrollRestoration = 'manual';
  }

  function waitForExit(signal) {
    if (reducedMotion.matches) {
      return Promise.resolve();
    }
    return new Promise((resolve) => {
      const timer = window.setTimeout(resolve, 150);
      signal.addEventListener('abort', () => {
        window.clearTimeout(timer);
        resolve();
      }, { once: true });
    });
  }

  function absolutiseLinks(region, pageUrl) {
    region.querySelectorAll('a[href]').forEach((link) => {
      link.href = new URL(link.getAttribute('href'), pageUrl).href;
    });
  }

  async function navigate(target, mode) {
    // A slow older request must never replace a newer destination, including
    // while the exit transition is pending. Abort and sequence checks agree.
    activeRequest?.abort();
    document.querySelector('[data-page-content]')?.removeAttribute('data-transition');
    const controller = new AbortController();
    activeRequest = controller;
    const number = ++navigationNumber;

    try {
      const response = await fetch(target.href, {
        signal: controller.signal,
        headers: { Accept: 'text/html' },
      });
      if (!response.ok || !response.headers.get('content-type')?.includes('text/html')) {
        throw new Error('Navigation did not return an HTML page');
      }

      const fetched = new DOMParser().parseFromString(await response.text(), 'text/html');
      const nextNavigation = fetched.querySelector('[data-site-navigation]');
      const nextMain = fetched.querySelector('[data-page-content]');
      const nextSiteData = fetched.getElementById('site-data');
      // The persistent exercise closure belongs to one module. Validate the
      // fetched shell before swapping regions; its site-data is not installed.
      if (!nextNavigation || !nextMain || !nextMain.querySelector('h1')
          || !nextSiteData || JSON.parse(nextSiteData.textContent).module !== moduleId) {
        throw new Error('Navigation page is missing the expected regions');
      }

      absolutiseLinks(nextNavigation, target.href);
      absolutiseLinks(nextMain, target.href);
      if (controller.signal.aborted || number !== navigationNumber) {
        return;
      }

      const currentMain = document.querySelector('[data-page-content]');
      currentMain.dataset.transition = 'leaving';
      await waitForExit(controller.signal);
      if (controller.signal.aborted || number !== navigationNumber) {
        return;
      }

      nextMain.dataset.transition = 'entering';
      // Native disclosure state needs no storage or additional event handlers.
      // Newly active ancestors still open when the destination changes section.
      const currentNavigation = document.querySelector('[data-site-navigation]');
      const openNodes = new Map([...currentNavigation.querySelectorAll('[data-nav-node]')]
        .map((node) => [node.dataset.navNode, node.open]));
      nextNavigation.querySelectorAll('[data-nav-node]').forEach((node) => {
        node.open = node.hasAttribute('data-nav-current') || (openNodes.get(node.dataset.navNode) ?? node.open);
      });
      nextNavigation.querySelector('[data-course-navigator]').open = navigatorForPage().open;
      document.querySelector('[data-site-navigation]').replaceWith(nextNavigation);
      currentMain.replaceWith(nextMain);
      if (mode === 'push') {
        history.pushState(null, '', target.href);
      }
      renderedUrl = new URL(window.location.href);
      document.title = fetched.title;
      // answer-key travels inside main; initialise() reads it from the new
      // form and restores responses without re-executing either script.
      window.AgrarianExercises?.initialise();

      const heading = nextMain.querySelector('h1');
      heading.tabIndex = -1;
      heading.focus({ preventScroll: true });
      window.scrollTo(0, Math.max(0, nextMain.getBoundingClientRect().top + window.scrollY - 16));
      requestAnimationFrame(() => {
        requestAnimationFrame(() => nextMain.removeAttribute('data-transition'));
      });
    } catch (error) {
      if (!controller.signal.aborted && number === navigationNumber) {
        // A failed enhancement must still reach the ordinary URL. popstate
        // has already changed that URL, so reload it instead of pushing again.
        if (mode === 'push') {
          window.location.assign(target.href);
        } else {
          window.location.reload();
        }
      }
    } finally {
      if (activeRequest === controller) {
        activeRequest = null;
      }
    }
  }

  // Delegate once to document because both link-containing regions are
  // replaced. Modified clicks, fragments and other excluded links stay native.
  document.addEventListener('click', (event) => {
    if (event.defaultPrevented || event.button !== 0
        || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return;
    }
    const link = event.target.closest('a[href]');
    if (!link || link.hasAttribute('download') || link.hasAttribute('data-no-enhance')
        || link.relList.contains('external')
        || (link.target && link.target !== '_self')) {
      return;
    }
    const target = new URL(link.href, window.location.href);
    if (!['http:', 'https:'].includes(target.protocol)
        || target.origin !== window.location.origin || target.hash
        || !target.pathname.startsWith(moduleRoot)
        || target.href === window.location.href) {
      return;
    }
    event.preventDefault();
    void navigate(target, 'push');
  });

  window.addEventListener('popstate', () => {
    const target = new URL(window.location.href);
    // Fragment history changes need no fetch or main-region replacement.
    if (target.pathname + target.search === renderedUrl.pathname + renderedUrl.search) {
      return;
    }
    void navigate(target, 'pop');
  });
})();
