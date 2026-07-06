export function buildMemoryBrief(decisions) {
  const active = decisions.filter((d) => d.status === 'active');
  const lines = [];
  lines.push('# Institutional Memory Brief');
  lines.push(`Generated: ${new Date().toISOString().slice(0, 10)}`);
  lines.push('');
  lines.push(`${active.length} active decision(s) on record.`);
  lines.push('');
  for (const d of active) {
    lines.push(`## ${d.title}`);
    lines.push(`- Decided: ${d.decidedAt || '—'} by ${d.decidedBy || '—'}`);
    lines.push(`- Summary: ${d.summary || ''}`);
    lines.push(`- Reasoning: ${d.reasoning || ''}`);
    if (d.sources?.length) {
      lines.push('- Sources:');
      for (const s of d.sources) {
        const link = s.url ? `[${s.externalRef || s.sourceType}](${s.url})` : s.externalRef || s.sourceType;
        lines.push(`  - ${link}`);
      }
    }
    if (d.alternativesConsidered?.length) {
      lines.push('- Alternatives rejected:');
      for (const a of d.alternativesConsidered) {
        lines.push(`  - ${a.option} — _${a.whyRejected}_`);
      }
    }
    lines.push('');
  }
  return lines.join('\n');
}