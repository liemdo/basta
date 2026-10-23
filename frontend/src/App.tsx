import { useEffect, useRef, useState, type FormEvent } from "react"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

type UserRow = {
  user_id: string
  balance: string
}

type CreditView = {
  task_id: string
  user_id: string
  amount: string
  status: string
  error?: string | null
}

type FieldError = {
  loc?: unknown
  msg?: string
}

type ErrorPayload = {
  detail?: string | FieldError[]
}

function sanitizeAmount(raw: string): string {
  const value = raw.replace(/-/g, "").replace(/[^\d.]/g, "")
  const dot = value.indexOf(".")
  if (dot === -1) return value
  const whole = value.slice(0, dot)
  const fraction = value.slice(dot + 1).replace(/\./g, "").slice(0, 2)
  return `${whole}.${fraction}`
}

function errorMessage(payload: ErrorPayload | null): string {
  if (payload && typeof payload.detail === "string") return payload.detail
  if (
    payload &&
    Array.isArray(payload.detail) &&
    payload.detail[0] &&
    payload.detail[0].msg
  ) {
    return payload.detail[0].msg
  }
  return "Request failed."
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

export default function App() {
  const [userId, setUserId] = useState("")
  const [amount, setAmount] = useState("")
  const [userError, setUserError] = useState("")
  const [amountError, setAmountError] = useState("")
  const [status, setStatus] = useState("")
  const [users, setUsers] = useState<UserRow[]>([])
  const [busy, setBusy] = useState(false)
  const submitting = useRef(false)

  async function loadUsers() {
    const response = await fetch("/users")
    if (!response.ok) {
      setAmountError("Could not load balances.")
      return
    }
    const payload = (await response.json()) as { users?: UserRow[] }
    setUsers(payload.users ?? [])
  }

  useEffect(() => {
    loadUsers().catch(() => setAmountError("Could not load balances."))
  }, [])

  function showRequestError(payload: ErrorPayload | null) {
    setStatus("")
    if (payload && Array.isArray(payload.detail)) {
      let placed = false
      for (const item of payload.detail) {
        const loc = Array.isArray(item.loc) ? item.loc : []
        const field = loc.length > 0 ? String(loc[loc.length - 1]) : ""
        if (field === "user_id") {
          setUserError(item.msg ?? "")
          placed = true
        } else if (field === "amount") {
          setAmountError(item.msg ?? "")
          placed = true
        }
      }
      if (placed) return
    }
    setAmountError(errorMessage(payload))
  }

  async function pollCredit(taskId: string) {
    const deadline = Date.now() + 30000
    while (Date.now() < deadline) {
      const response = await fetch(`/credits/${encodeURIComponent(taskId)}`)
      if (!response.ok) {
        setStatus("")
        setAmountError("Could not read credit status.")
        return
      }
      const credit = (await response.json()) as CreditView
      if (credit.status === "processed") {
        setStatus(`Processed ${credit.amount} for ${credit.user_id}.`)
        await loadUsers()
        return
      }
      if (credit.status === "failed") {
        setStatus("")
        setAmountError(credit.error || "Credit failed.")
        return
      }
      setStatus("Processing. The balance updates when the worker finishes.")
      await sleep(1000)
    }
    setStatus("Still processing. The balance will update after the worker finishes.")
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting.current) return
    setUserError("")
    setAmountError("")
    const submittedUserId = userId
    const nextAmount = sanitizeAmount(amount).replace(/\.$/, "")
    if (!(Number(nextAmount) > 0)) {
      setAmount(nextAmount)
      setAmountError("Amount must be greater than 0.")
      return
    }
    setUserId("")
    setAmount("")
    submitting.current = true
    setBusy(true)
    try {
      const response = await fetch("/credits", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify({ user_id: submittedUserId, amount: nextAmount }),
      })
      const payload = (await response.json()) as ErrorPayload & { task_id?: string }
      if (!response.ok) {
        showRequestError(payload)
        return
      }
      setStatus("Accepted. Waiting for the worker.")
      await pollCredit(payload.task_id ?? "")
    } catch {
      setStatus("")
      setAmountError("Could not reach the credit API.")
    } finally {
      submitting.current = false
      setBusy(false)
    }
  }

  return (
    <main className="mx-auto flex min-h-svh w-full max-w-xl flex-col gap-6 px-5 py-10">
      <div className="space-y-1">
        <h1 className="font-heading text-2xl font-semibold tracking-tight">Credits</h1>
        <p className="text-sm text-muted-foreground">
          No sign-in. Type a user id and an amount. The balance changes after the worker finishes.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Add credit</CardTitle>
          <CardDescription>The request returns as soon as the credit is accepted.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="grid gap-4" onSubmit={onSubmit}>
            <div className="grid gap-2">
              <Label htmlFor="user-id">User id</Label>
              <Input
                id="user-id"
                name="user_id"
                required
                maxLength={128}
                pattern="[A-Za-z0-9_\\-]+"
                autoComplete="off"
                value={userId}
                aria-invalid={userError ? true : undefined}
                onChange={(event) => {
                  setUserId(event.target.value)
                  setUserError("")
                }}
              />
              {userError ? (
                <p className="text-sm text-destructive" role="alert">
                  {userError}
                </p>
              ) : null}
            </div>
            <div className="grid gap-2">
              <Label htmlFor="amount">Amount</Label>
              <Input
                id="amount"
                name="amount"
                required
                inputMode="decimal"
                autoComplete="off"
                value={amount}
                aria-invalid={amountError ? true : undefined}
                onChange={(event) => {
                  setAmount(sanitizeAmount(event.target.value))
                  setAmountError("")
                }}
              />
              {amountError ? (
                <p className="text-sm text-destructive" role="alert">
                  {amountError}
                </p>
              ) : null}
            </div>
            <Button type="submit" size="lg" className="w-full" disabled={busy}>
              Add credit
            </Button>
          </form>
        </CardContent>
      </Card>

      <p className="sr-only" role="status">
        {status}
      </p>
      {status ? (
        <Alert>
          <AlertDescription className="text-foreground">{status}</AlertDescription>
        </Alert>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Balances</CardTitle>
          <CardDescription>Committed balances only. Processing credits stay off this list.</CardDescription>
        </CardHeader>
        <CardContent>
          {users.length === 0 ? (
            <p className="text-sm text-muted-foreground">No balances yet.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>User</TableHead>
                  <TableHead className="text-right">Balance</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {users.map((user) => (
                  <TableRow key={user.user_id}>
                    <TableCell>{user.user_id}</TableCell>
                    <TableCell className="text-right tabular-nums">{user.balance}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </main>
  )
}
