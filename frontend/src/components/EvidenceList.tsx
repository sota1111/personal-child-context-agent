// Renders the verbatim Evidence a finding / action carries. Evidence is always shown
// so every displayed conclusion is traceable to the source text it came from — the UI
// never paraphrases it into a medical or safety assertion.
export default function EvidenceList({
  label,
  items,
}: {
  label: string
  items: string[]
}) {
  if (!items || items.length === 0) return null
  return (
    <div className="evidence">
      <span className="evidence-label">{label}</span>
      <ul>
        {items.map((e, i) => (
          <li key={i}>{e}</li>
        ))}
      </ul>
    </div>
  )
}
