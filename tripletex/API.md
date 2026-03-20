# Tripletex API Reference For NM i AI

This document is a task-focused summary of the Tripletex API as exposed through the NM i AI Tripletex task.

Primary source material saved locally:

- `tripletex/docs/task-overview.html`
- `tripletex/docs/task-sandbox.html`
- `tripletex/docs/task-endpoint.html`
- `tripletex/docs/task-scoring.html`
- `tripletex/docs/task-examples.html`
- `tripletex/docs/api-docs.html`
- `tripletex/docs/openapi.json`

The OpenAPI spec identifies itself as:

- Title: `Tripletex API`
- Version: `2.74.00`
- Server: `https://kkpqfuj-amager.tripletex.dev/v2`
- Paths in spec: `546`

This file does not try to restate all 546 paths. It focuses on the paths and data models that are directly relevant to the NM i AI task docs and the task families described there.

## 1. What The API Is

Tripletex exposes a large REST API for accounting, CRM, invoicing, travel expenses, projects, ledger operations, payroll-related bookkeeping, and related business objects.

In the competition, your agent does not call the public base URL directly. It receives:

- a fresh `base_url`
- a fresh `session_token`

in each submission request, and must call the provided proxy URL.

In practice, this means:

- the API surface is the normal Tripletex v2 REST API
- authentication comes from the competition request
- every submission runs against a brand new company/account state

## 2. Authentication

There are three separate authentication contexts:

### 2.1 Web UI login

Used only by a human in the browser.

- Login email from sandbox card
- First-time password setup via "Forgot password"
- Used for manual exploration of the Tripletex UI

This is not what the agent uses when calling the API.

### 2.2 Tripletex API authentication

Used by the agent for all Tripletex API calls.

- Auth type: HTTP Basic Auth
- Username: `0`
- Password: `<session_token>`

Competition docs explicitly require:

- use the provided `base_url`
- use the provided `session_token`
- do not use some other hardcoded Tripletex URL

### 2.3 Your own `/solve` endpoint API key

Optional protection for your Cloud Run service.

- Header: `Authorization: Bearer <your-api-key>`

This protects your endpoint from the public internet. It is unrelated to Tripletex API auth.

## 3. Competition-Side Input And Output

Your deployed endpoint receives:

```json
{
  "prompt": "Opprett en ansatt med navn Ola Nordmann, ola@example.org. Han skal være kontoadministrator.",
  "files": [
    {
      "filename": "faktura.pdf",
      "content_base64": "JVBERi0xLjQg...",
      "mime_type": "application/pdf"
    }
  ],
  "tripletex_credentials": {
    "base_url": "https://<provided-per-submission>/v2",
    "session_token": "abc123..."
  }
}
```

Important implications:

- `prompt` is the actual task instruction
- `files` may be empty, or may contain PDFs/images
- `tripletex_credentials` are the live credentials for this single submission

Your endpoint must return:

```json
{
  "status": "completed"
}
```

with HTTP 200, within 300 seconds.

## 4. Common API Shape

Tripletex follows a fairly regular pattern.

### 4.1 List/search endpoints

Pattern:

- `GET /entity`

Common features:

- many filter query params
- `from` and `count` for pagination
- `sorting`
- `fields` for sparse field selection

Typical response shape:

```json
{
  "fullResultSize": 123,
  "from": 0,
  "count": 100,
  "versionDigest": "...",
  "values": [ ... ]
}
```

This is the dominant read pattern for search-and-resolve tasks.

### 4.2 Get-by-id endpoints

Pattern:

- `GET /entity/{id}`

Typical response shape:

```json
{
  "value": { ...entity... }
}
```

### 4.3 Create endpoints

Pattern:

- `POST /entity`

Typical behavior:

- takes a JSON entity object
- returns HTTP 201
- wraps the created entity in `{ "value": ... }`

### 4.4 Update endpoints

Pattern:

- `PUT /entity/{id}`

Typical behavior:

- takes a JSON entity object
- returns HTTP 200
- often expects `id`, `version`, or a full enough object shape to update correctly

### 4.5 Delete endpoints

Pattern:

- `DELETE /entity/{id}`

Typical behavior:

- returns HTTP 204
- no response body of practical value

### 4.6 Action-style endpoints

Tripletex also uses state-changing "action endpoints" rather than only pure CRUD.

Examples directly relevant to task workflows:

- `PUT /order/{id}/:invoice`
- `PUT /invoice/{id}/:payment`
- `POST /supplierInvoice/{invoiceId}/:addPayment`

These are important because they may be more efficient and more semantically correct than building the same result through multiple generic mutations.

## 5. Cross-Cutting Query Mechanics

The task docs explicitly highlight these API patterns:

- `fields`: select only needed fields
- `from`, `count`: pagination
- targeted search filters: reduce unnecessary list scans

Operationally, this matters because competition scoring rewards:

- correctness
- few API calls
- few or no 4xx mistakes

So the normal query style should be:

1. use the most specific filter you can
2. request only fields you need
3. keep list results small

## 6. Core Task-Relevant Domains

Below are the most important domains for the competition task categories.

## 6.1 Employees

Main endpoints:

- `GET /employee`
- `POST /employee`
- `GET /employee/{id}`
- `PUT /employee/{id}`

What it does:

- create employee records
- find employees by name/email/number
- update employee details
- manage project-manager-like relationships via employee references in other entities

Relevant search inputs:

- `id`
- `firstName`
- `lastName`
- `employeeNumber`
- `email`
- `departmentId`
- `hasSystemAccess`
- `fields`

Relevant entity fields seen in schema:

- `firstName`
- `lastName`
- `displayName`
- `employeeNumber`
- `email`
- `phoneNumberMobile`
- `department`
- `allowInformationRegistration`
- `userType`

Typical outputs:

- list response with `values: [Employee]`
- wrapper response with `value: Employee`

Related workflows:

- create employee
- update contact info
- resolve employee by email/name before linking elsewhere
- identify managers/owners for departments/projects

Notes:

- The task docs mention administrator-role-style tasks.
- The high-level employee schema exposes `userType` and access-related search flags, but exact admin-role handling should be verified in the sandbox for real task coverage.

## 6.2 Customers

Main endpoints:

- `GET /customer`
- `POST /customer`
- `GET /customer/{id}`
- `PUT /customer/{id}`
- `DELETE /customer/{id}` (beta)

What it does:

- create and manage customers
- find customer records by organization number, name, email, account manager, etc.
- provide linkage targets for orders, invoices, and projects

Relevant search inputs:

- `id`
- `customerAccountNumber`
- `organizationNumber`
- `email`
- `invoiceEmail`
- `customerName`
- `accountManagerId`

Relevant entity fields:

- `name`
- `organizationNumber`
- `isCustomer`
- `isSupplier`
- `department`
- `accountManager`
- `email`
- `invoiceEmail`
- `phoneNumber`
- `phoneNumberMobile`
- `invoiceSendMethod`
- `invoicesDueIn`

Typical outputs:

- list of `Customer`
- wrapped `Customer`

Related workflows:

- create customer first, then use customer ID when creating order/project/invoice
- update invoice email or contact data
- search before create to avoid duplicates

## 6.3 Products

Main endpoints:

- `GET /product`
- `POST /product`
- `GET /product/{id}`
- `PUT /product/{id}`
- `DELETE /product/{id}`

What it does:

- create catalog/service/product records
- provide line items for orders and invoices

Relevant search inputs:

- `productNumber`
- `name`
- `ean`
- `supplierId`
- `vatTypeId`
- `departmentId`
- `accountId`

Relevant entity fields:

- `name`
- `number`
- `description`
- `orderLineDescription`
- `ean`
- `costExcludingVatCurrency`
- `priceExcludingVatCurrency`
- `priceIncludingVatCurrency`
- `productUnit`
- `department`

Related workflows:

- create product before adding order lines
- resolve product by number/name before invoicing
- update pricing or metadata

## 6.4 Orders

Main endpoints:

- `GET /order`
- `POST /order`
- `GET /order/{id}`
- `PUT /order/{id}`
- `DELETE /order/{id}`
- `PUT /order/{id}/:invoice`

What it does:

- represent commercial orders and order lines
- bridge customers/products/projects to invoicing
- act as the most natural precursor to an invoice in many flows

Relevant search inputs:

- `id`
- `number`
- `customerId`
- `orderDateFrom`
- `orderDateTo`
- `isClosed`

Relevant entity fields:

- `customer`
- `contact`
- `department`
- `orderDate`
- `project`
- `invoiceComment`
- `orderGroups`
- `orderLines`
- `invoicesDueIn`

Critical action workflow:

- `PUT /order/{id}/:invoice`

This endpoint creates a new invoice from an existing order and supports parameters such as:

- `invoiceDate`
- `sendToCustomer`
- `sendType`
- `paymentTypeId`
- `paidAmount`
- `createBackorder`
- `invoiceIdIfIsCreditNote`

This is likely more efficient than manually reconstructing an invoice when an order already exists.

## 6.5 Invoices

Main endpoints:

- `GET /invoice`
- `POST /invoice`
- `GET /invoice/{id}`
- `PUT /invoice/{id}/:payment`

What it does:

- create outgoing invoices
- search invoices by date/number/customer/voucher
- register payments
- hold relationships to orders, order lines, projects, travel reports, and vouchers

Relevant search inputs:

- `id`
- `invoiceDateFrom`
- `invoiceDateTo`
- `invoiceNumber`
- `kid`
- `voucherId`
- `customerId`

Relevant invoice fields:

- `invoiceNumber`
- `invoiceDate`
- `invoiceDueDate`
- `customer`
- `orders`
- `orderLines`
- `travelReports`
- `projectInvoiceDetails`
- `voucher`
- `paymentTypeId`
- `creditedInvoice`
- `invoiceComment`

Critical creation note from the spec:

- `POST /invoice` can create the invoice directly
- related `Order` and `OrderLine` objects may already exist
- or they may be embedded inside the invoice object

Critical payment workflow:

- `PUT /invoice/{id}/:payment`

Parameters include:

- `paymentDate`
- `paymentTypeId`
- `paidAmount`
- `paidAmountCurrency`

This is the main outgoing-invoice payment-registration action exposed in the spec.

Related workflows:

- customer -> order -> invoice
- direct invoice creation from embedded order lines
- invoice payment registration
- credit-note-related flows through invoice references/action parameters

## 6.6 Travel Expenses

Main endpoints:

- `GET /travelExpense`
- `POST /travelExpense`
- `GET /travelExpense/{id}`
- `PUT /travelExpense/{id}`
- `DELETE /travelExpense/{id}`

What it does:

- create, update, and delete travel expense reports
- link expenses to employees, departments, projects, and eventually accounting artifacts

Relevant search inputs:

- `employeeId`
- `departmentId`
- `projectId`
- `projectManagerId`
- `departureDateFrom`
- `returnDateTo`
- `state`

Relevant fields:

- `employee`
- `project`
- `department`
- `travelDetails`
- `paymentCurrency`
- `voucher`
- `invoice`
- `paymentAmount`

Related workflows:

- create expense from prompt/attachment data
- find an existing expense and delete it
- update a draft/submitted expense

## 6.7 Projects

Main endpoints:

- `GET /project`
- `POST /project`
- `GET /project/{id}`
- `PUT /project/{id}` (beta)
- `DELETE /project/{id}` (beta)

What it does:

- create customer-linked or internal projects
- connect customers, departments, project managers, invoice defaults, and project-level billing logic

Relevant search inputs:

- `name`
- `number`
- `projectManagerId`
- `departmentId`
- `customerId`
- `isClosed`
- `isFixedPrice`

Relevant fields:

- `name`
- `number`
- `description`
- `projectManager`
- `department`
- `customer`
- `startDate`
- `endDate`
- `isClosed`
- `isReadyForInvoicing`
- `isInternal`
- `isOffer`
- `isFixedPrice`
- `invoiceComment`
- `invoiceReceiverEmail`
- `accessType`

Related workflows:

- create project linked to customer
- set project manager / department
- use project on orders, travel expenses, postings, or invoices

## 6.8 Departments

Main endpoints:

- `GET /department`
- `POST /department`
- `GET /department/{id}`
- `PUT /department/{id}`
- `DELETE /department/{id}`

What it does:

- manage organizational departments
- provide a reusable reference in employees, customers, products, orders, projects, and postings

Relevant search inputs:

- `id`
- `name`
- `departmentNumber`
- `departmentManagerId`

Relevant fields:

- `name`
- `departmentNumber`
- `departmentManager`
- `displayName`
- `isInactive`
- `businessActivityTypeId`

Related workflows:

- create department
- assign department manager
- attach department to employees/projects/customers/products/orders

Note:

- The task docs mention "enable accounting modules" around departments.
- The department resource itself exists in the API, but module-enablement behavior should be verified in sandbox because that can involve system configuration beyond simple CRUD.

## 6.9 Ledger Accounts

Main endpoints:

- `GET /ledger/account`
- `POST /ledger/account`

What it does:

- expose and create ledger/chart-of-account records

Relevant search inputs:

- `number`
- `isBankAccount`
- `ledgerType`
- `saftCode`

Relevant fields:

- `number`
- `name`
- `description`
- `type`
- `ledgerType`
- `vatType`
- `currency`
- `isCloseable`
- `isApplicableForSupplierInvoice`
- `requireReconciliation`
- `isBankAccount`

Related workflows:

- inspect account numbers before posting or voucher creation
- create missing account structures if a task requires it

## 6.10 Ledger Postings

Main endpoint:

- `GET /ledger/posting`

What it does:

- query accounting postings across dimensions and time windows

Relevant filters:

- `dateFrom`
- `dateTo`
- `openPostings`
- `accountId`
- `supplierId`
- `customerId`
- `employeeId`
- `departmentId`
- `projectId`
- `productId`

Relevant posting fields:

- `voucher`
- `customer`
- `project`
- `product`
- `department`
- `invoiceNumber`
- `termOfPayment`
- `systemGenerated`

Related workflows:

- reconciliation tasks
- find postings tied to a voucher/invoice/customer/project
- verify effect of a voucher or correction

## 6.11 Ledger Vouchers

Main endpoints:

- `GET /ledger/voucher`
- `POST /ledger/voucher`
- `GET /ledger/voucher/{id}`
- `PUT /ledger/voucher/{id}`
- `DELETE /ledger/voucher/{id}`

What it does:

- create, inspect, update, and delete accounting vouchers
- create postings as a side effect
- support correction/reversal-like workflows

Relevant filters:

- `id`
- `number`
- `numberFrom`
- `numberTo`
- `typeId`
- `dateFrom`
- `dateTo`

Relevant fields:

- `date`
- `number`
- `description`
- `voucherType`
- `reverseVoucher`
- `postings`
- `document`
- `attachment`
- `externalVoucherNumber`
- `vendorInvoiceNumber`

Important behavior from the spec:

- creating a voucher also creates postings
- gross amounts are used
- amounts should be rounded to two decimals
- updating a voucher regenerates postings with `guiRow == 0`

Related workflows:

- create manual ledger adjustments
- reverse or correct bad entries
- inspect accounting consequences of previous actions

## 7. Response Patterns You Should Expect

### 7.1 Search/list responses

Usually:

- `fullResultSize`
- `from`
- `count`
- `versionDigest`
- `values`

### 7.2 Single-entity responses

Usually:

- `value`

### 7.3 Mutations

- `POST`: usually `201` with wrapper
- `PUT`: usually `200` with wrapper
- `DELETE`: usually `204`

## 8. Related Workflows Across Entities

These are the high-value workflows the task docs implicitly point to.

### 8.1 Customer -> Order -> Invoice

Typical chain:

1. resolve or create customer
2. resolve or create product(s)
3. create order with order lines
4. create invoice, either:
   - via `POST /invoice`, or
   - via `PUT /order/{id}/:invoice`

### 8.2 Invoice -> Payment

Typical chain:

1. resolve invoice
2. call `PUT /invoice/{id}/:payment`
3. verify invoice state or related ledger/voucher outcome if needed

### 8.3 Employee / Manager / Department Setup

Typical chain:

1. resolve or create employee
2. resolve or create department
3. link employee as department manager or project manager
4. update the target object

### 8.4 Customer -> Project

Typical chain:

1. resolve customer
2. resolve project manager / department
3. create project linked to customer

### 8.5 Travel Expense Lifecycle

Typical chain:

1. resolve employee/project/department
2. create or search travel expense
3. update or delete as required

### 8.6 Ledger Correction

Typical chain:

1. search vouchers/postings
2. identify target entry
3. update/delete/create reversal or corrective voucher
4. verify with voucher/posting queries

## 9. API Properties That Matter For The Competition

### 9.1 The account starts empty every submission

This is crucial. Many tasks require prerequisites:

- customer before project
- customer/product/order before invoice
- employee before department/project manager linkage

### 9.2 Search is part of the task solution

Even create-heavy tasks often require:

- duplicate avoidance
- lookup for managers/customers/projects
- finding an existing object to update/delete

### 9.3 Efficiency matters

Because scoring rewards low call count and low error count, use the API in ways that minimize:

- broad scans
- trial-and-error mutations
- redundant verification reads

### 9.4 The API is broader than the task docs

The spec is much larger than the competition subset. For the competition, the high-value surface is:

- employee
- customer
- product
- order
- invoice
- travelExpense
- project
- department
- ledger/account
- ledger/posting
- ledger/voucher
- a few action endpoints such as order->invoice and invoice->payment

## 10. Practical Notes For Documentation Readers

- The Swagger UI page is only a loader. The actual spec is in `tripletex/docs/openapi.json`.
- The OpenAPI spec itself does not appear to declare the competition proxy auth in a top-level security object. The competition docs are the authoritative source for using Basic Auth `0:<session_token>`.
- For many task families, sandbox exploration is still necessary to identify the minimal working payload for perfect scoring, especially around:
  - employee/system-access/admin-role details
  - department/module enablement details
  - credit-note and correction flows
  - attachment-derived bookkeeping tasks
