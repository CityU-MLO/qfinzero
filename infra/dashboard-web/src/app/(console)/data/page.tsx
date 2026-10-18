import { redirect } from "next/navigation";

// Storage status is a tab of the data setup utility.
export default function DataPage() {
  redirect("/data-setup#status");
}
