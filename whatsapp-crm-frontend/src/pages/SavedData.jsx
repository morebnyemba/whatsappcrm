// pages/SavedData.jsx
import { useEffect, useState } from 'react'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Skeleton } from '@/components/ui/skeleton'

const DataSkeleton = () => (
  <div className="space-y-4">
    <Skeleton className="h-8 w-full" />
    <Skeleton className="h-8 w-full" />
    <Skeleton className="h-8 w-full" />
  </div>
)

export default function SavedData() {
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setTimeout(() => {
      setData([
        { id: 1, client: "Acme Corp", lastMessage: "Hello!", timestamp: new Date() },
        { id: 2, client: "Tech Inc", lastMessage: "Need support", timestamp: new Date() }
      ])
      setLoading(false)
    }, 1500)
  }, [])

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Saved Data</h1>
      {loading ? (
        <DataSkeleton />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Client</TableHead>
              <TableHead>Last Message</TableHead>
              <TableHead>Timestamp</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.map((item) => (
              <TableRow key={item.id}>
                <TableCell>{item.client}</TableCell>
                <TableCell>{item.lastMessage}</TableCell>
                <TableCell>
                  {item.timestamp.toLocaleDateString()}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}