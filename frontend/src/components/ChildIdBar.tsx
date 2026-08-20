// Small inline control shown on each page to view/change the active child id.
export default function ChildIdBar({
  childId,
  onChange,
}: {
  childId: string
  onChange: (id: string) => void
}) {
  return (
    <label className="child-bar">
      <span>対象の子ID</span>
      <input
        type="text"
        value={childId}
        onChange={(e) => onChange(e.target.value)}
        aria-label="対象の子ID"
      />
    </label>
  )
}
