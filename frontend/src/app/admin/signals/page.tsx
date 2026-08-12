import { redirect } from "next/navigation";


export default function PrivateSignalsPage() {
  redirect("/positions/history");
}
