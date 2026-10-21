import React, { useEffect, useState } from 'react';
import { categories, helpRegistry, searchTopics, helpPath } from './registry';
import { followHelp } from './ContextHelp';

const routeTopic = () => {
  try { return decodeURIComponent(window.location.pathname.replace(/^\/help\/?/, '').replace(/\/$/, '')); }
  catch { return '__invalid__'; }
};
export default function HelpCenter() {
  const [query, setQuery] = useState(''), [category, setCategory] = useState('');
  const [topicId, setTopicId] = useState(routeTopic);
  useEffect(() => {
    const follow = () => { setTopicId(routeTopic()); setQuery(''); setCategory(''); };
    window.addEventListener('popstate', follow);
    return () => window.removeEventListener('popstate', follow);
  }, []);
  useEffect(() => { document.getElementById('help-article-title')?.focus({ preventScroll: true }); }, [topicId]);
  const topic = helpRegistry[topicId], matches = searchTopics(query, category);
  return <div className="ms-help-center">
    <nav aria-label="Help categories" className="ms-help-categories"><strong>Help &amp; Guide</strong>
      <button type="button" aria-pressed={!category} onClick={() => setCategory('')}>All topics</button>
      {categories.map(value => <button type="button" key={value} aria-pressed={category === value} onClick={() => setCategory(value)}>{value}</button>)}
    </nav>
    <div className="ms-help-content">
      <p className="ms-sub">Rules and explanations verified against the application. Recorded values, derived arithmetic and illustrative examples are labelled separately.</p>
      <label className="ms-help-search">Search Help &amp; Guide<input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search ATR, entry cutoff, trailing stop…" /></label>
      {(!topic || query || category) && <section aria-label="Help search results"><h3>{category || 'Browse topics'} <small>({matches.length})</small></h3>
        {topicId && !topic && <p role="status">This help topic was not found. Choose a documented topic below.</p>}
        <ul className="ms-help-results">{matches.map(item => <li key={item.id}><a href={helpPath(item.id)} onClick={event => followHelp(event, item.id)}>{item.title}</a><small>{item.category}</small><p>{item.summary}</p></li>)}</ul>
        {!matches.length && <p role="status">No matching topics. Try fewer words or another category.</p>}
      </section>}
      {topic && !query && !category && <HelpArticle topic={topic} />}
    </div>
  </div>;
}
export function HelpArticle({ topic }) {
  const anchors = [['meaning', 'What it means'], ['rules', 'How Market Signal uses it'], ['configuration', 'Configuration and effective time'], ...(topic.example ? [['example', 'Illustrative example']] : []), ['related', 'Related topics']];
  return <article className="ms-help-article" aria-labelledby="help-article-title">
    <span className="ms-label">{topic.category}</span><h2 id="help-article-title" tabIndex={-1}>{topic.title}</h2>
    <nav aria-label="Article contents">{anchors.map(([id, text]) => <a key={id} href={`#help-${id}`}>{text}</a>)}</nav>
    <h3 id="help-meaning">What it means</h3><p>{topic.summary}</p>
    <h3 id="help-rules">How Market Signal uses it</h3><ul>{topic.rules.map(rule => <li key={rule}>{rule}</li>)}</ul>
    {topic.formula && <p className="ms-help-calculation">{topic.formula}</p>}
    <h3 id="help-configuration">Configuration and effective time</h3><p>{topic.configurable}</p>
    <p>Documented defaults describe a new installation. Use recorded configuration snapshots to explain a historical decision; an unavailable value is not assumed to equal the default.</p>
    {topic.example && <><h3 id="help-example">Illustrative example</h3><p>{topic.example}</p></>}
    <h3 id="help-related">Related topics</h3><ul>{topic.related.map(id => <li key={id}><a href={helpPath(id)} onClick={event => followHelp(event, id)}>{helpRegistry[id]?.title ?? id}</a></li>)}</ul>
    <a href="/help" onClick={event => { if (!event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey && event.button === 0) { event.preventDefault(); window.history.pushState({}, '', '/help'); window.dispatchEvent(new PopStateEvent('popstate')); } }}>Browse all help topics</a>
  </article>;
}
