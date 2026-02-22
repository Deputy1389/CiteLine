# =====================================================
# Oracle Cloud - Create LineCite Worker Instance (V8 - Micro)
# =====================================================

$oci = "C:\Users\paddy\bin\oci.exe"
$compartmentId = "ocid1.tenancy.oc1..aaaaaaaa5od5ri7irim5c6zhcgrc2ofqfdpyumjvs3if6vohgbphkv32v4ga"
$displayName = "linecite-worker-micro"

Write-Host "🚀 Creating LineCite Worker (Micro) on Oracle Cloud..."

# 1. Get availability domain
$ads = & $oci iam availability-domain list --compartment-id $compartmentId | ConvertFrom-Json
$availabilityDomain = $ads.data[0].name
Write-Host "   Using: $availabilityDomain"

# 2. Get Ubuntu x86_64 image (for Micro instance)
Write-Host "💿 Finding Ubuntu 22.04 x86_64 image..."
$images = & $oci compute image list --compartment-id $compartmentId --operating-system "Canonical Ubuntu" --operating-system-version "22.04" --shape "VM.Standard.E2.1.Micro" --limit 1 | ConvertFrom-Json
if ($null -eq $images.data -or $images.data.Count -eq 0) {
    $images = & $oci compute image list --compartment-id $compartmentId --operating-system "Canonical Ubuntu" --limit 10 | ConvertFrom-Json
}
$imageId = $images.data[0].id
Write-Host "   Using Image: $($images.data[0].'display-name')"

# 3. Create VCN (Will reuse if already exists from previous attempt)
Write-Host "🌐 Creating/Finding Virtual Cloud Network..."
$vcnSearch = & $oci network vcn list --compartment-id $compartmentId --display-name "linecite-vcn" | ConvertFrom-Json
if ($vcnSearch.data.Count -gt 0) {
    $vcnId = $vcnSearch.data[0].id
    Write-Host "   Reusing existing VCN: $vcnId"
} else {
    $vcn = & $oci network vcn create --compartment-id $compartmentId --cidr-block "10.0.0.0/16" --display-name "linecite-vcn" --dns-label "linecite" --wait-for-state AVAILABLE | ConvertFrom-Json
    $vcnId = $vcn.data.id
}

# 4. Get Internet Gateway
$igwSearch = & $oci network internet-gateway list --compartment-id $compartmentId --vcn-id $vcnId | ConvertFrom-Json
if ($igwSearch.data.Count -gt 0) {
    $igwId = $igwSearch.data[0].id
} else {
    $igw = & $oci network internet-gateway create --compartment-id $compartmentId --vcn-id $vcnId --is-enabled true --display-name "linecite-igw" --wait-for-state AVAILABLE | ConvertFrom-Json
    $igwId = $igw.data.id
}

# 5. Get/Update route table
$rtSearch = & $oci network route-table list --compartment-id $compartmentId --vcn-id $vcnId | ConvertFrom-Json
$rtId = $rtSearch.data[0].id
$routeRules = "[{`"destination`":`"0.0.0.0/0`",`"networkEntityId`":`"$igwId`"}]"
$routeRules | Out-File -FilePath "rules.json" -Encoding ascii
& $oci network route-table update --rt-id $rtId --route-rules "file://rules.json" --force | Out-Null

# 6. Get/Create Security List
$egress = "[{`"destination`":`"0.0.0.0/0`",`"protocol`":`"all`",`"isStateless`":false}]"
$ingress = "[{`"source`":`"0.0.0.0/0`",`"protocol`":`"6`",`"tcpOptions`":{`"destinationPortRange`":{`"min`":22,`"max`":22}},`"isStateless`":false}]"
$slSearch = & $oci network security-list list --compartment-id $compartmentId --vcn-id $vcnId --display-name "linecite-sl" | ConvertFrom-Json
if ($slSearch.data.Count -gt 0) {
    $slId = $slSearch.data[0].id
} else {
    $egress | Out-File -FilePath "egress.json" -Encoding ascii
    $ingress | Out-File -FilePath "ingress.json" -Encoding ascii
    $sl = & $oci network security-list create --compartment-id $compartmentId --vcn-id $vcnId --display-name "linecite-sl" --egress-security-rules "file://egress.json" --ingress-security-rules "file://ingress.json" --wait-for-state AVAILABLE | ConvertFrom-Json
    $slId = $sl.data.id
}

# 7. Get/Create Public Subnet
$subnetSearch = & $oci network subnet list --compartment-id $compartmentId --vcn-id $vcnId --display-name "linecite-subnet" | ConvertFrom-Json
if ($subnetSearch.data.Count -gt 0) {
    $subnetId = $subnetSearch.data[0].id
} else {
    $slIds = "[`"$slId`"]"
    $slIds | Out-File -FilePath "slids.json" -Encoding ascii
    $subnet = & $oci network subnet create --compartment-id $compartmentId --vcn-id $vcnId --cidr-block "10.0.0.0/24" --display-name "linecite-subnet" --dns-label "public" --route-table-id $rtId --security-list-ids "file://slids.json" --wait-for-state AVAILABLE | ConvertFrom-Json
    $subnetId = $subnet.data.id
}

# 8. Get SSH key
$keyPath = "$env:USERPROFILE\.ssh\oracle-worker"

# 9. Launch Micro Instance (Always Free)
Write-Host "💻 Launching Micro instance (Intel/AMD Micro - Always Free)..."
$instance = & $oci compute instance launch --compartment-id $compartmentId --availability-domain $availabilityDomain --shape "VM.Standard.E2.1.Micro" --display-name $displayName --image-id $imageId --subnet-id $subnetId --assign-public-ip true --ssh-authorized-keys-file "$keyPath.pub" --wait-for-state RUNNING | ConvertFrom-Json
$instanceId = $instance.data.id

# 10. Get public IP
Write-Host "⏳ Waiting for public IP..."
Start-Sleep -Seconds 20
$vnicAttachments = & $oci compute vnic-attachment list --compartment-id $compartmentId --instance-id $instanceId | ConvertFrom-Json
$vnicId = $vnicAttachments.data[0].'vnic-id'
$vnic = & $oci network vnic get --vnic-id $vnicId | ConvertFrom-Json
$publicIp = $vnic.data.'public-ip'

# Cleanup
Remove-Item "rules.json", "egress.json", "ingress.json", "slids.json" -ErrorAction SilentlyContinue

Write-Host "SUCCESS!"
Write-Host "Instance ID: $instanceId"
Write-Host "Public IP: $publicIp"
Write-Host "Connect with: ssh -i $keyPath ubuntu@$publicIp"
