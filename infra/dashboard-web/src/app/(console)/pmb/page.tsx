import { redirect } from "next/navigation";

// Broker settings live on the Broker page; the stand-alone PMB terminal is
// served by PMB itself at /svc/pmb/ui/.
export default function PmbPage() {
  redirect("/broker#settings");
}
