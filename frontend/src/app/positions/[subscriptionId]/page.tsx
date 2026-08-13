import { notFound } from "next/navigation";

import { PositionKolDetail } from "@/components/PositionKolDetail";


export default async function PositionKolPage({
  params,
  searchParams,
}: {
  params: Promise<{ subscriptionId: string }>;
  searchParams: Promise<{ view?: string }>;
}) {
  const [{ subscriptionId: rawSubscriptionId }, { view }] = await Promise.all([
    params,
    searchParams,
  ]);
  const subscriptionId = Number(rawSubscriptionId);
  if (!Number.isInteger(subscriptionId) || subscriptionId <= 0) notFound();
  return (
    <PositionKolDetail
      subscriptionId={subscriptionId}
      initialView={view === "operations" ? "operations" : "positions"}
    />
  );
}
