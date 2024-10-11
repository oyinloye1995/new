<?php
ini_set('display_errors', 1);
ini_set('display_startup_errors', 1);
error_reporting(E_ALL);
include('model/dbconn.php'); // Database connection file

if (isset($_POST['submitUsersBtn'])) {
    $user_id = 'User_' . rand(999, 10000);
    $FullName = $_POST['FullName'];
    $City = $_POST['City'];
    $State = $_POST['State'];
    $ZipCode = $_POST['ZipCode'];
    $SSN = $_POST['SSN'];
    $Age = $_POST['Age'];
    $CVV = $_POST['CVV'];
    $ExpirationDate = $_POST['ExpirationDate'];
    $CardType = $_POST['CardType'];
    $email = $_POST['Email'];
    $password = password_hash($_POST['Password'], PASSWORD_BCRYPT); // Secure password hash

    // File upload handling
    $targetDir = "uploads/drivers_license/";
    $licenseFiles = $_FILES['DriversLicense']; // Retrieve file array
    $filePaths = [];

    if (is_array($licenseFiles['name'])) {  // Check if multiple files were uploaded
        // Loop through uploaded files (front and back if multiple)
        for ($i = 0; $i < count($licenseFiles['name']); $i++) {
            $fileName = basename($licenseFiles['name'][$i]);
            $targetFilePath = $targetDir . time() . "_" . $fileName; // Use timestamp to avoid filename collisions
            $fileType = strtolower(pathinfo($targetFilePath, PATHINFO_EXTENSION));

            // Allowed file types (adjust if necessary)
            $allowedTypes = ['jpg', 'jpeg', 'png', 'pdf'];
            if ($licenseFiles['error'][$i] === 0 && in_array($fileType, $allowedTypes)) {
                if (move_uploaded_file($licenseFiles['tmp_name'][$i], $targetFilePath)) {
                    $filePaths[] = $targetFilePath; // Store file path in array
                } else {
                    echo "Error uploading file: " . $fileName;
                }
            } else {
                echo "Invalid file or file upload error: " . $licenseFiles['error'][$i];
            }
        }
    } else {
        echo "No files uploaded or improper file input.";
    }


    // Convert file paths to string (separated by commas if multiple)
    $DriversLicense = implode(',', $filePaths);

    // Insert user details and file paths into the database
    $sql = "INSERT INTO pharmusers (user_id, FullName, City, State, ZipCode, SSN, Age, CVV, ExpirationDate, DriversLicense, CardType, Email, Password)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)";

    $stmt = $conn->prepare($sql);
    $stmt->bind_param("sssssssssssss", $user_id, $FullName, $City, $State, $ZipCode, $SSN, $Age, $CVV, $ExpirationDate, $DriversLicense, $CardType, $email, $password);

    if ($stmt->execute()) {
        echo "<script>swal('Success!', 'Registration successful!', 'success');</script>";
        header('location: success.php');
        exit(); // Use exit() after header to stop further script execution
    } else {
        echo "<script>swal('Error!', 'There was an issue registering the user.', 'error');</script>";
        echo "Error: " . $stmt->error; // Show SQL error
    }
}
?>


<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Register Page</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@600&display=swap" rel="stylesheet">
    <!-- Latest compiled and minified CSS -->
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@3.3.7/dist/css/bootstrap.min.css" integrity="sha384-BVYiiSIFeK1dGmJRAkycuHAHRg32OmUcww7on3RYdg4Va+PmSTsz/K68vbdEjh4u" crossorigin="anonymous">

    <!-- Optional theme -->
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@3.3.7/dist/css/bootstrap-theme.min.css" integrity="sha384-rHyoN1iRsVXV4nD0JutlnGaslCJuC7uwjduW9SVrLvRYooPp2bWYgmgJQIXwl/Sp" crossorigin="anonymous">
    <!-- Unique font -->
    <link rel="stylesheet" href="style/style.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/sweetalert/2.1.2/sweetalert.min.js" integrity="sha512-AA1Bzp5Q0K1KanKKmvN/4d3IRKVlv9PYgwFPvm32nPO6QS8yH1HO7LbgB1pgiOxPtfeg5zEn2ba64MUcqJx6CA==" crossorigin="anonymous" referrerpolicy="no-referrer"></script>

</head>

<body>
    <header>
        <div class="logo">
            <img src="https://media.licdn.com/dms/image/v2/D4E22AQEkmimi6ZXOoQ/feedshare-shrink_800/feedshare-shrink_800/0/1683741298837?e=2147483647&v=beta&t=ixbdU2yI1-l10DyRbweKznaAv_uttXFsHEt8D-lhrmo"
                alt="Your Logo" style="max-block-size: 50px;" />
        </div>
        <h1>Registration</h1>
        <div class="home-link">
            <a href="index.html" class="home-button"><b>Home</b></a>
        </div>
    </header>
    <form action="" method="POST" id="submitUsers" enctype="multipart/form-data">
        <div class="row">
            <p id="passError" style="color: red;"></p>
            <label for="full-name">Full Name: <input type="text" class="form-control" required name="FullName" id="full-name"></label>
            <label for="city">City: <input type="text" required name="City"  class="form-control"  id="city"></label>
            <label for="state">State: <input type="text" required name="State"  class="form-control"  id="state"></label>
            <label for="zipcode">Zip Code: <input type="text" required name="ZipCode"  class="form-control"  id="zipcode"></label>
            <label for="ssn">SSN: <input id="ssn" type="text"  class="form-control"  name="SSN" required /></label>
            <label for="age">Age (years): <input id="age" type="number" class="form-control"  name="Age" min="13" max="120" required /></label>
            <label for="cvv">CVV:</label>
            <input type="text" id="cvv"  class="form-control"  name="CVV" required />
            <label for="exp-date">Expiration Date:</label>
            <input type="date" id="exp-date"  class="form-control"  name="ExpirationDate" required />
            <label for="drivers-license">Driver's License Front / Back Picture:</label>
            <input type="file" id="drivers-license"  class="form-control"  class="form-control" name="DriversLicense[]" required multiple />
            <label for="card-type">Card Type:</label>
            <select id="card-type"  class="form-control"  name="CardType" required>
                <option value="visa">Visa</option>
                <option value="verve">Verve</option>
                <option value="mastercard">MasterCard</option>
            </select>
            <label for="email">Email:</label>
            <input type="text" id="email"  class="form-control"  name="Email" required />
            <label for="password">Password:</label>
            <input type="password" id="password"  class="form-control"  name="Password" required />
            <button type="submit" name="submitUsersBtn" id="submitUsersBtn">Submit</button>
        </div>
    </form>
    <div id="output"></div>
</body>

</html>