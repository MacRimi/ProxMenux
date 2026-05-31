import Hero from "@/components/hero"
import Resources from "@/components/resources"
import SupportProject from "@/components/support-project"
import Footer from "@/components/footer"


export default function Home() {
  return (
    <div className="min-h-screen bg-gradient-to-b from-gray-900 to-gray-800 text-white pt-16">
      <Hero />
      <Resources />
      <SupportProject />
      <Footer />
    </div>
  )
}
