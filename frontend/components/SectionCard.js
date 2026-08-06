import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

// Titled card section (icon + title + optional description and header action).
// Shared by the Operations page, farm detail, and the evidence panel.
// `size="section"` promotes the heading to the 18/24 scale for major panels.
export default function SectionCard({
  title,
  icon,
  description,
  action,
  size = "default",
  children,
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-2 space-y-0">
        <div className="min-w-0">
          <CardTitle size={size}>
            {icon}
            {title}
          </CardTitle>
          {description && <p className="mt-0.5 text-meta text-muted">{description}</p>}
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}
