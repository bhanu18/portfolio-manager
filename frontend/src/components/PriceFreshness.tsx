/** This is the stored price update time, not a promise of a live quote. */
export function PriceFreshness({ timestamp }: { timestamp: string | null }) {
  const date = timestamp ? new Date(timestamp) : null;
  const valid = date && Number.isFinite(date.getTime());
  return (
    <p className="price-freshness">
      {valid ? (
        <>
          Price updated{" "}
          <time dateTime={timestamp!}>
            {date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}
          </time>
        </>
      ) : (
        "Price update time unavailable"
      )}
    </p>
  );
}
