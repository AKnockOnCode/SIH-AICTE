import { useTitle } from "../components/layout";
import { Empty, LinkButton } from "../components/ui";

export function NotFoundPage() {
  useTitle("Page not found");
  return (
    <Empty title="This page does not exist" action={<LinkButton to="/" variant="primary">Go to the command dashboard</LinkButton>}>
      The link may be out of date. Use the search box in the header to find an institution or case.
    </Empty>
  );
}
