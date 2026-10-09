import { Navigate, useLocation, useParams } from "react-router-dom";

/** Preserve bookmarked asset symbols and URL context. */
export function LegacyAssetRedirect() {
  const { symbol } = useParams();
  const { search, hash } = useLocation();
  return <Navigate replace to={`/holdings/${encodeURIComponent(symbol ?? "")}${search}${hash}`} />;
}
