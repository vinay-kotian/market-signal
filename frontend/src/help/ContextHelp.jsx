import React, { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { helpRegistry, helpPath } from './registry';
import { explainDecision } from './reasons';

export function followHelp(event, topicId) {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault(); event.stopPropagation();
  window.history.pushState({}, '', helpPath(topicId));
  window.dispatchEvent(new PopStateEvent('popstate'));
  window.scrollTo?.({ top: 0, behavior: 'instant' });
}

export default function ContextHelp({ topicId, decision, label }) {
  const [open, setOpen] = useState(false);
  const trigger = useRef(null), dialog = useRef(null);
  const titleId = useId();
  const explanation = decision ? explainDecision(decision) : null;
  const topic = explanation?.topic ?? helpRegistry[topicId] ?? helpRegistry['troubleshooting/unknown'];
  const title = explanation?.title ?? topic.title;
  useEffect(() => {
    if (!open) return;
    const previous = trigger.current;
    dialog.current?.querySelector('button')?.focus();
    const onKey = event => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); setOpen(false); }
      if (event.key === 'Tab') {
        const fields = [...dialog.current.querySelectorAll('button, a[href], input, select, [tabindex="0"]')];
        const first = fields[0], last = fields.at(-1);
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    };
    document.addEventListener('keydown', onKey, true);
    const before = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey, true);
      document.body.style.overflow = before;
      if (previous?.isConnected) previous.focus({ preventScroll: true });
    };
  }, [open]);
  return <>
    <button ref={trigger} className="ms-context-help" type="button" aria-label={label ?? `Why? ${title}`}
      aria-haspopup="dialog" aria-expanded={open} title={title}
      onClick={event => { event.preventDefault(); event.stopPropagation(); setOpen(value => !value); }}><span aria-hidden="true" /></button>
    {open && createPortal(<div className="ms-help-backdrop" onClick={event => { event.stopPropagation(); if (event.target === event.currentTarget) setOpen(false); }}>
      <section className="ms-help-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} ref={dialog} onClick={event => event.stopPropagation()}>
        <div className="ms-help-dialog-heading"><h2 id={titleId}>{title}</h2><button type="button" aria-label="Close help" onClick={() => setOpen(false)}>×</button></div>
        {explanation ? <>
          <h3>Why it happened</h3><p>{explanation.why}</p>
          <h3>Decision values</h3>
          <dl>{explanation.facts.map((fact, index) => <div key={`${fact.label}-${index}`}><dt>{fact.label}<small>{fact.kind}</small></dt><dd>{String(fact.value)}</dd></div>)}</dl>
          {explanation.calculations.map((text, index) => <p className="ms-help-calculation" key={index}>{text}</p>)}
          {explanation.missing && <p className="ms-help-unavailable">Some decision details were not recorded. Current settings and system defaults are not substituted for missing historical values.</p>}
        </> : <><p>{topic.summary}</p>{topic.formula && <p className="ms-help-calculation">{topic.formula}</p>}</>}
        <h3>Responsible rule</h3><p>{topic.summary}</p>
        <h3>Configuration</h3><p>{topic.configurable}</p>
        <a className="ms-help-guide-link" href={topic.url} onClick={event => { setOpen(false); followHelp(event, topic.id); }}>Read {topic.title} →</a>
      </section>
    </div>, document.body)}
  </>;
}

export function DecisionHelp(props) { return <ContextHelp decision={props} />; }
