import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

// Titled card section (icon + title + optional description and header action).
// Shared by the Operations page, farm detail, and the evidence panel.
export default function SectionCard({ title, icon, description, action, children }) {
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-2 space-y-0">
        <div>
          <CardTitle>
            {icon}
            {title}
          </CardTitle>
          {description && <p className="mt-0.5 text-xs text-gray-500">{description}</p>}
        </div>
        {action}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}
