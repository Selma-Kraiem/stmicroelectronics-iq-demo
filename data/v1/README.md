# V1 Microsoft IQ demo assets

All assets in this directory are fictional STMicroelectronics demonstration data.
They must not be presented as customer, production, or live manufacturing records.

| IQ layer | Repository asset | Runtime destination |
| --- | --- | --- |
| Exposure function | `code_interpreter/SiC_AUTO_Shipments.xlsx` plus three CSV projections | Fab Intelligence calculates it through a typed Agent Framework Python function; the CSVs support future Code Interpreter retesting after its file-ownership issue is resolved |
| Foundry IQ | `foundry_iq/*.md` | Indexed in the V1 Foundry knowledge base |
| Fabric IQ | `fabric_iq/FabricIQ_Data_Model.md` | Seed the Fabric ontology when licensing and capacity are available; otherwise load the same tables through the local adapter |
| Work IQ | `work_iq/WorkIQ_SharePoint_Ops_Handbook.md` | Optional publication to a delegated presenter's `Quality Ops` SharePoint library |

Only the Markdown knowledge sources are staged; the duplicate PDFs from the source
asset pack are intentionally excluded.

The shipment workbook was rebuilt as a standard OOXML `.xlsx` because the supplied
file used an OLE container despite its `.xlsx` extension. The rebuilt workbook
preserves the `Shipments`, `Inventory`, `LotMaster`, and `README` sheets and contains
no formulas.

All delegated OneDrive, SharePoint, Work IQ, and Teams operations use the signed-in
presenter's permissions. Never commit downloaded tenant content.
