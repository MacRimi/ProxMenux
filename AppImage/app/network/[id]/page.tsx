import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { NetworkTrafficChart } from "@/components/charts/network-traffic-chart"

const Page = ({ params }) => {
  const { id } = params
  const timeframe = "1h" // Example value, you may need to adjust this based on your application logic

  return (
    <div>
      {/* Other components or code here */}

      <Card>
        <CardHeader>
          <CardTitle>Network Traffic</CardTitle>
        </CardHeader>
        <CardContent>
          <NetworkTrafficChart timeframe={timeframe} interfaceName={id} refreshInterval={30000} />
        </CardContent>
      </Card>

      {/* Other components or code here */}
    </div>
  )
}

export default Page
